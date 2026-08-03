import json
import os
from typing import List, Dict, Any
from enum import Enum, auto

class FeatureStatus(Enum):
    DISCOVERED = "DISCOVERED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

from dataclasses import dataclass

@dataclass
class StepLog:
    step_id: int
    action_id: int
    prev_page_description: str
    action_description: str
    widget_signature: str
    next_page_description: str
    result: str
    next_page_brief_description: str = None
    state_change_summary: str = None
    prev_state_views_signatures: List[str] = None
    current_state_views_signatures: List[str] = None
    prev_screenshot_path: str = None
    current_screenshot_path: str = None

@dataclass
class Action:
    name: str
    widget_index: int = None
    input_text: str = None
    swipe_direction: str = None
class Feature:
    def __init__(self,
                
                 description: str,
                 source_activity: str,
                 initial_page_description: str = None,
                 initial_page_brief_description: str = None,
                 widget_label: int = None,
                 confidence: float = 0.5):
        self.widget_label = widget_label
        self.widget_str = None
        self.description = description
        self.source_activity = source_activity
        self.confidence = confidence
        self.initial_page_brief_description = initial_page_brief_description
        self.status = FeatureStatus.DISCOVERED
        self.executed_summary = []
        self.next_event_name = None
        self.next_event = None
        self.next_event_widget_index = None
        self.next_event_description = None
        self.next_event_signature = None
        self.initial_page_description = initial_page_description
        self.execution_steps = 0
        self.max_execution_steps = 13
        self.inexecutable_count = 0
        self.max_inexecutable_count = 5

        self.failed_widgets = []
        self.start_time = None
        self.end_time = None

        self.initial_state_views_signatures = []
        self.final_state_views_signatures = []


    def start_execution(self):
        self.status = FeatureStatus.IN_PROGRESS
        self.start_time = self.get_current_time()
    
    def complete(self, success: bool):
        self.status = FeatureStatus.COMPLETED if success else FeatureStatus.FAILED
        self.end_time = self.get_current_time()
    def get_current_time(self):
        from datetime import datetime
        return datetime.now().strftime("%Y%m%d%H%M%S")
    def add_executed_summary(self, prev_page_description: str, action_description: str, current_page_description: str):
        self.executed_summary.append({
            "step_id": len(self.executed_summary) + 1,
            "prev_page_description": prev_page_description,
            "action_description": action_description,
            "current_page_description": current_page_description
        })
    def add_final_state(self, final_state: str):
        self.executed_summary.append({
            "final_page_description": final_state
        })
        
    def to_dict(self):
        return {
            "description": self.description,
            "source_activity": self.source_activity,
            "status": self.status.name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "initial_page_description": self.initial_page_description,
            "initial_page_brief_description": self.initial_page_brief_description,
            "executed_summary": self.executed_summary,
            "first_state_views_signatures": self.initial_state_views_signatures,
            "final_state_views_signatures": self.final_state_views_signatures,
        }
    
    def __repr__(self):
        return f"Feature(description={self.description}, status={self.status}, conf={self.confidence:.2f})"
    
from typing import List
from .feature import Feature, FeatureStatus

class FeaturePool:
    def __init__(self,path:str):
        self.features: List[Feature] = []
        self.features = self.load_features_from_file(path)
        self.path = path


    def add(self, feature: Feature):
        self.features.append(feature)

    def append_features(self, features: List[Feature]):
        self.features.extend(features)

    def get_discovered(self) -> List[Feature]:
        return [f for f in self.features if f.status == FeatureStatus.DISCOVERED]

    def get_in_progress(self) -> List[Feature]:
        return [f for f in self.features if f.status == FeatureStatus.IN_PROGRESS]

    def get_completed(self) -> List[Feature]:
        return [f for f in self.features if f.status == FeatureStatus.COMPLETED]

    def get_failed(self) -> List[Feature]:
        return [f for f in self.features if f.status == FeatureStatus.FAILED]

    def has_pending(self) -> bool:
        return any(f.status in [FeatureStatus.DISCOVERED, FeatureStatus.IN_PROGRESS]
                   for f in self.features)
    
    def load_features_from_file(self, feature_path:str) -> List[Feature]:

        import json
        if not os.path.exists(feature_path) or os.path.getsize(feature_path) == 0:
            return []
        try:
            with open(feature_path, 'r', encoding='utf-8-sig') as f:
                feature_list = json.load(f)
        except UnicodeDecodeError as e:
            raise UnicodeDecodeError(f"Failed to decode UTF-8-SIG from file {feature_path}: {e}")
        for feature_dict in feature_list:
            feature = Feature(
                description=feature_dict['description'],
                source_activity=feature_dict['source_activity'],
                initial_page_description=feature_dict.get('initial_page_description'),
                initial_page_brief_description=feature_dict.get('initial_page_brief_description'),
                confidence=feature_dict.get('confidence', 0.5)
            )
            feature.status = FeatureStatus[feature_dict.get('status', 'DISCOVERED')]
            feature.executed_summary = feature_dict.get('executed_summary', "")
            feature.initial_state_views_signatures = feature_dict.get('first_state_views_signatures', [])
            feature.final_state_views_signatures = feature_dict.get('final_state_views_signatures', [])
            self.add(feature)
        return self.features
    
    def output_features_to_json(self):
        output_path = self.path
        features = [f.to_dict() for f in self.features if f.status == FeatureStatus.COMPLETED or f.status == FeatureStatus.FAILED]
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(features, f, ensure_ascii=False, indent=2)


    def __repr__(self):
        return f"FeaturePool(size={len(self.features)})"
