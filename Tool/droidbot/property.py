from enum import Enum, auto
import json
from typing import List, Dict, Any
import re
from .input_event import LongTouchEvent, TouchEvent, KeyEvent, IntentEvent, SetTextEvent
from droidbot.device_state import DeviceState




class PropertyStatus(Enum):
    # PENDING = auto()
    # VERIFIED = auto()
    # REJECTED = auto()
    # SKIPPED = auto()
    DISCOVERED = "DISCOVERED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class Property:
    def __init__(self,
                 name: str,
                 pre: str = None,
                 interaction: List[str] = None,
                 post: str = None,
                 signals: List[str] = None,
                 confidence: float = 0.5):
        self.name = name
        self.feature_name = None
        self.pre = pre
        self.interaction = interaction
        self.post = post
        self.next_event_name = None
        self.next_event = None
        self.next_event_widget_index = None
        self.signals = signals or []
        self.confidence = confidence
        self.status = PropertyStatus.DISCOVERED
        self.history: List[Dict[str, Any]] = []
        self.progress: int = 0

        self.executed_steps: int = 0
        self.max_steps: int = 10

        self.inexecutable_count = 0
        self.max_inexecutable_count = 3
        
        self.executed_summary = ""

        self.widget_signature_list = []
        self.initial_state_views_signatures = []
        self.final_state_views_signatures = []
        self.step_state_views_signatures = []

    def start_execution(self):
        self.status = PropertyStatus.IN_PROGRESS
    
    def complete(self, success: bool):
        self.status = PropertyStatus.COMPLETED if success else PropertyStatus.FAILED

    def is_applicable(self, ui_state: "DeviceState") -> bool:
        return all(self._eval_expr(expr, ui_state) for expr in self.pre)

    def _eval_expr(self, expr: str, ui_state: "DeviceState") -> bool:
        return Property._eval_expr_static(expr, ui_state)

    @staticmethod
    def _eval_expr_static(expr: str, ui_state: "DeviceState") -> bool:

        expr = expr.strip()

        if expr.startswith("(") and expr.endswith(")"):
            return Property._eval_expr_static(expr[1:-1], ui_state)

        # AND
        if " AND " in expr:
            return all(Property._eval_expr_static(p, ui_state)
                       for p in Property._split_expr(expr, "AND"))

        # OR
        if " OR " in expr:
            return any(Property._eval_expr_static(p, ui_state)
                       for p in Property._split_expr(expr, "OR"))

        return Property._check_condition(expr, ui_state)

    @staticmethod
    def _split_expr(expr: str, op: str):
        parts, buf, depth = [], "", 0
        tokens = expr.split()
        for t in tokens:
            if "(" in t:
                depth += t.count("(")
            if ")" in t:
                depth -= t.count(")")
            if depth == 0 and t == op:
                parts.append(buf.strip())
                buf = ""
            else:
                buf += (" " + t)
        if buf.strip():
            parts.append(buf.strip())
        return parts

    @staticmethod
    def _check_condition(condition: str, ui_state: "DeviceState") -> bool:
        try:

            cond = condition.strip()

            if cond.startswith("exists["):
                inside = cond[len("exists["):-1]
                key, value = inside.split("=", 1)
                widget = ui_state.find_widget(key.strip(), value.strip('"\''))
                return widget is not None

            if cond.startswith("not exists["):
                inside = cond[len("not exists["):-1]
                key, value = inside.split("=", 1)
                widget = ui_state.find_widget(key.strip(), value.strip('"'))
                return widget is None

            if cond.startswith("visible["):
                inside = cond[len("visible["):-1]
                key, value = inside.split("=", 1)
                widget = ui_state.find_widget(key.strip(), value.strip('"'))
                return widget is not None and ui_state._DeviceState__safe_dict_get(widget, "visible", False)

            if cond.startswith("enabled["):
                inside = cond[len("enabled["):-1]
                key, value = inside.split("=", 1)
                widget = ui_state.find_widget(key.strip(), value.strip('"'))
                return widget is not None and ui_state._DeviceState__safe_dict_get(widget, "enabled", False)
        except Exception as e:
            print(f"Error evaluating condition '{condition}': {e}")
            return False
        return False

    @staticmethod
    def parse_interaction(interaction: str, current_state: "DeviceState"):
        match = re.match(r"(\w+)\[(.*)\]", interaction)
        if not match:
            return None

        action, args_str = match.groups()
        args = {}
        for pair in args_str.split(","):
            if "=" in pair:
                k, v = pair.strip().split("=", 1)
                args[k.strip()] = v.strip('"')

        if action == "click":
            target_id = args.get("id") or args.get("text") or args.get("desc") or args.get("class")
            if not target_id:
                return None
            key = "id" if "id" in args else "text" if "text" in args else "desc" if "desc" in args else "class"
            widget = current_state.find_widget(key, target_id)
            return TouchEvent(view=widget) if widget else None
        if action == "long_click":
            target_id = args.get("id") or args.get("text") or args.get("desc") or args.get("class")
            if not target_id:
                return None
            key = "id" if "id" in args else "text" if "text" in args else "desc" if "desc" in args else "class"
            widget = current_state.find_widget(key, target_id)
            return LongTouchEvent(view=widget) if widget else None
        
        if action == "set_text":
            target_id = args.get("id") or args.get("text") or args.get("desc")
            text = args.get("input")
            widget = None
            if target_id:
                key = "id" if "id" in args else "text" if "text" in args else "desc"
                widget = current_state.find_widget(key, target_id)
            return SetTextEvent(view=widget, text=text) if widget else None

        if action == "Press":
            return KeyEvent(name=args.get("name", "ENTER"))

        if action == "Intent":
            return IntentEvent(intent=args)

        return None

    def validate(self, after: "DeviceState") -> bool:
        results = [(expr, self._eval_expr(expr, after)) for expr in self.post]
        success = all(ok for _, ok in results)
        self.history.append({
            "after": after.to_dict(),
            "post_results": results,
            "success": success
        })
        self.status = PropertyStatus.COMPLETED if success else PropertyStatus.FAILED
        return success
    
    def validate_post(self, ui_state: "DeviceState") -> bool:
        return all(self._eval_expr(expr, ui_state) for expr in self.post)

    # def record_execution(self, before_state: Dict[str, Any], after_state: Dict[str, Any], success: bool):
    #     self.history.append({
    #         "before": before_state,
    #         "after": after_state,
    #         "success": success
    #     })
    #     self.status = PropertyStatus.VERIFIED if success else PropertyStatus.REJECTED

    def to_dict(self):
        return {
            "feature_name": self.feature_name,
            "name": self.name,
            "pre": self.pre,
            "interaction": self.interaction,
            "post": self.post,
            "widget_signature_list": self.widget_signature_list,
            "initial_state_views_signatures": self.initial_state_views_signatures,
            "final_state_views_signatures": self.final_state_views_signatures,
            "step_state_views_signatures": self.step_state_views_signatures,
            "status": self.status.name
        }

    def __repr__(self):
        return (f"Hypothesis(function={self.name}, status={self.status}, "
                f"conf={self.confidence:.2f})")


class PropertyPool:
    def __init__(self, path: str):
        self.properties: List[Property] = []
        self.path = path
        self.properties = self.load_properties_from_json(path)

    def add(self, hypothesis: Property):
        self.properties.append(hypothesis)

    # def applicable_hypotheses(self, ui_state: "DeviceState") -> List[Property]:
    #     return [h for h in self.hypotheses
    #             if h.status == PropertyStatus.DISCOVERED and h.is_applicable(ui_state)]

    def __repr__(self):
        return f"HypothesisPool(size={len(self.properties)})"
    
    def load_properties_from_json(self, property_path: str) -> List[Property]:
        import os
        if not os.path.exists(property_path) or os.path.getsize(property_path) == 0:
            return []
        with open(property_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for item in data:
            prop = Property(
                name=item.get("name", ""),
                pre=item.get("pre", []),
                interaction=item.get("interaction", []),
                post=item.get("post", [])
            )
            prop.status = PropertyStatus[item.get("status", "DISCOVERED")]
            prop.feature_name = item.get("feature_name", "")
            prop.widget_signature_list = item.get("widget_signature_list", [])
            prop.initial_state_views_signatures = item.get("initial_state_views_signatures", [])
            prop.final_state_views_signatures = item.get("final_state_views_signatures", [])
            prop.step_state_views_signatures = item.get("step_state_views_signatures", [])
            self.add(prop)
        return self.properties

    def output_properties_to_json(self):
        output_path = self.path
        properties = [f.to_dict() for f in self.properties if f.status == PropertyStatus.COMPLETED]
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(properties, f, ensure_ascii=False, indent=2)

