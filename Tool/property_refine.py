#!/usr/bin/env python3
import argparse
import html
import json
import os
import re
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional


@dataclass
class ScreenshotInfo:
    caption: str
    image_path: str


@dataclass
class PropertyRepairInput:
    property_index: str
    property_name: str
    feature_name: str
    property_description: str
    property_code: str
    screenshots: List[ScreenshotInfo]
    error_message: str
    feature_trace: str = ""


def extract_execution_step_from_caption(caption: str) -> Optional[int]:
    match = re.match(r"\s*(\d+)-\d+\.", caption or "")
    if not match:
        return None
    return int(match.group(1))


def extract_execution_step_from_screenshots(screenshots: List[ScreenshotInfo]) -> Optional[int]:
    for shot in screenshots:
        step = extract_execution_step_from_caption(shot.caption)
        if step is not None:
            return step
    return None


def extract_bug_report_href(cell_html: str, clean_html_dir: str) -> str:
    match = re.search(r"""<a[^>]*href=(['"])(?P<href>.*?)\1""", cell_html, re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    href = html.unescape(match.group("href").strip())
    return os.path.normpath(os.path.join(clean_html_dir, href))


def load_error_message_from_bug_report(
    bug_report_path: str,
    property_name: str,
    execution_step: Optional[int],
    cache: Dict[str, Dict[str, str]],
) -> str:
    if not bug_report_path or not os.path.exists(bug_report_path):
        return ""
    if bug_report_path not in cache:
        cache[bug_report_path] = {}
    cache_key = f"{property_name}@@{execution_step if execution_step is not None else 'none'}"
    if cache_key not in cache[bug_report_path]:
        cache[bug_report_path][cache_key] = parse_error_message_for_property_execution(
            read_text(bug_report_path),
            property_name,
            execution_step,
        )
    return cache[bug_report_path][cache_key]


def parse_error_message_for_property_execution(
    bug_report_html: str,
    property_name: str,
    execution_step: Optional[int],
) -> str:
    row_match = re.search(
        rf'<tr\s+class="[^"]*\bproperty-detail-row\b[^"]*"[^>]*data-detail-for="{re.escape(property_name)}"[^>]*>(?P<body>.*?)</tr>',
        bug_report_html,
        re.IGNORECASE | re.DOTALL,
    )
    if not row_match:
        return ""

    body = row_match.group("body") or ""
    td_match = re.search(r"<td[^>]*>(?P<td_body>.*?)</td>", body, re.IGNORECASE | re.DOTALL)
    td_body = td_match.group("td_body") if td_match else body

    if execution_step is None:
        return normalize_failure_report_text(strip_tags_preserve_newlines(td_body))

    step_badge_re = re.compile(
        r'Monkey Steps:\s*(?P<steps>[^<]+)',
        re.IGNORECASE | re.DOTALL,
    )

    pane_start_re = re.compile(r'<div\s+class="tab-pane[^"]*"[^>]*>', re.IGNORECASE)
    starts = list(pane_start_re.finditer(td_body))
    panes: List[str] = []
    for idx, start_match in enumerate(starts):
        start = start_match.start()
        end = starts[idx + 1].start() if idx + 1 < len(starts) else len(td_body)
        panes.append(td_body[start:end])

    for pane in panes:
        steps_match = step_badge_re.search(pane)
        if not steps_match:
            continue
        raw_steps = html.unescape(steps_match.group("steps"))
        steps = [int(s) for s in re.findall(r"\d+", raw_steps)]
        if execution_step in steps:
            return normalize_failure_report_text(strip_tags_preserve_newlines(pane))

    return normalize_failure_report_text(strip_tags_preserve_newlines(td_body))


@dataclass
class PropertyRepairResult:
    property_name: str
    property_index: str
    status: str
    classification: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    intent_restatement: str
    evidence: str
    next_actions: str
    root_causes: str
    minimal_core_behavior: str
    patched_description: str
    fixed_code: str
    raw_response: str
    prompt_preview: str
    error: str = ""


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def write_text(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def parse_property_indexes(property_index_arg: Optional[str]) -> List[str]:
    if not property_index_arg:
        return []
    parts = [part.strip() for part in property_index_arg.split(",")]
    return [part for part in parts if part]


def build_output_suffix(property_indexes: List[str]) -> str:
    return "_".join(property_indexes) if property_indexes else "all"


def strip_tags_preserve_newlines(value: str) -> str:
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    value = re.sub(r"</(div|p|pre|li|h\d|tr)>", "\n", value, flags=re.IGNORECASE)
    value = re.sub(r"<[^>]+>", "", value)
    value = html.unescape(value)
    value = value.replace("\r\n", "\n")
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def normalize_failure_report_text(value: str) -> str:
    """
    Keep only the core failure signal for prompting:
    - Error: ...
    - Traceback ...
    """
    value = html.unescape(value or "")
    value = value.replace("\r\n", "\n").replace("\r", "\n")

    normalized_lines: List[str] = []
    previous_blank = False
    for raw_line in value.split("\n"):
        line = raw_line.strip()
        if not line:
            if not previous_blank:
                normalized_lines.append("")
            previous_blank = True
            continue
        normalized_lines.append(line)
        previous_blank = False

    text = "\n".join(normalized_lines).strip()

    error_match = re.search(r"Error:\s*(.+)", text, re.IGNORECASE)
    traceback_match = re.search(
        r"(Traceback \(most recent call last\):.*)",
        text,
        re.IGNORECASE | re.DOTALL,
    )

    parts: List[str] = []
    if error_match:
        parts.append(f"Error: {error_match.group(1).strip()}")
    if traceback_match:
        traceback_text = traceback_match.group(1).strip()
        parts.append(traceback_text)

    if parts:
        return "\n\n".join(parts).strip()
    return text


def sanitize_filename(name: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return sanitized or "property"


def extract_code_from_response(response: str) -> str:
    response = (response or "").strip()
    if not response:
        return ""

    fenced = re.search(r"```(?:python)?\s*(.*?)```", response, re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()
    return response


def extract_classification_from_response(response: str) -> str:
    match = re.search(
        r"^Classification:\s*(REAL_BUG|PROPERTY_ERROR)\s*$",
        response or "",
        re.IGNORECASE | re.MULTILINE,
    )
    if not match:
        return ""
    return match.group(1).upper()


def extract_patched_code_from_response(response: str) -> str:
    response = response or ""
    section_match = re.search(
        r"Patched Property Code:\s*(.*)",
        response,
        re.IGNORECASE | re.DOTALL,
    )
    if not section_match:
        return ""
    return extract_code_from_response(section_match.group(1))


def extract_line_field(response: str, label: str) -> str:
    match = re.search(
        rf"^{re.escape(label)}:\s*(.*)$",
        response or "",
        re.IGNORECASE | re.MULTILINE,
    )
    if not match:
        return ""
    return match.group(1).strip()


def extract_block_field(response: str, label: str, next_labels: List[str]) -> str:
    response = response or ""
    next_pattern = "|".join(re.escape(item) for item in next_labels)
    if next_pattern:
        pattern = (
            rf"^{re.escape(label)}:\s*(.*?)"
            rf"(?=^(?:{next_pattern}):|\Z)"
        )
    else:
        pattern = rf"^{re.escape(label)}:\s*(.*)\Z"
    match = re.search(pattern, response, re.IGNORECASE | re.MULTILINE | re.DOTALL)
    if not match:
        return ""
    return match.group(1).strip()


def parse_shots(screenshots_html: str, clean_html_dir: str) -> List[ScreenshotInfo]:
    shot_re = re.compile(
        r"<div\s+class='shot'>.*?<img[^>]*src='(?P<src>[^']+)'[^>]*>.*?"
        r"<div\s+class='shot-cap'>(?P<cap>.*?)</div>.*?</div>",
        re.DOTALL | re.IGNORECASE,
    )
    shots: List[ScreenshotInfo] = []
    for match in shot_re.finditer(screenshots_html):
        rel_src = html.unescape(match.group("src").strip())
        caption = strip_tags_preserve_newlines(match.group("cap"))
        abs_path = os.path.normpath(os.path.join(clean_html_dir, rel_src))
        shots.append(ScreenshotInfo(caption=caption, image_path=abs_path))
    return shots


def select_property_execution_shots(
    shots: List[ScreenshotInfo],
    property_name: str,
) -> List[ScreenshotInfo]:
    """
    Keep only the screenshot sequence for this property execution:
    from '<property_name>: start' to '<property_name>: fail'.

    The clean.html screenshot strip may still contain unrelated leading context.
    If we cannot find an explicit property-qualified start/fail pair, fall back to
    the last plain 'start' ... 'fail' segment. If neither exists, return the
    original list unchanged.
    """
    if not shots:
        return shots

    property_start = f"{property_name}: start".lower()
    property_fail = f"{property_name}: fail".lower()

    start_idx: Optional[int] = None
    fail_idx: Optional[int] = None

    for idx, shot in enumerate(shots):
        cap = shot.caption.lower()
        if property_start in cap:
            start_idx = idx
        if property_fail in cap:
            fail_idx = idx

    if start_idx is not None and fail_idx is not None and start_idx <= fail_idx:
        return shots[start_idx : fail_idx + 1]

    plain_start_idx: Optional[int] = None
    plain_fail_idx: Optional[int] = None
    for idx, shot in enumerate(shots):
        cap = shot.caption.lower()
        if ": start" in cap or cap.endswith("start"):
            plain_start_idx = idx
        if ": fail" in cap or cap.endswith("fail"):
            plain_fail_idx = idx

    if plain_start_idx is not None and plain_fail_idx is not None and plain_start_idx <= plain_fail_idx:
        return shots[plain_start_idx : plain_fail_idx + 1]

    return shots


def parse_description(description_html: str) -> str:
    def normalize_desc_body(text: str) -> str:
        text = text.strip()
        text = re.sub(r"^#\s*(Precondition|Assertion)\s*:\s*", "", text, flags=re.IGNORECASE)
        return text.strip()

    parts: List[str] = []
    block_re = re.compile(
        r"<div\s+class='desc-block\s+(?P<kind>[^']+)'>(?P<body>.*?)</div>",
        re.DOTALL | re.IGNORECASE,
    )
    kind_prefix = {
        "desc-pre": "Precondition",
        "desc-body": "Function body",
        "desc-assert": "Assertion",
    }
    for match in block_re.finditer(description_html):
        kinds = match.group("kind").split()
        body = normalize_desc_body(strip_tags_preserve_newlines(match.group("body")))
        prefix = next((kind_prefix[k] for k in kinds if k in kind_prefix), "Description")
        if body:
            parts.append(f"{prefix}: {body}")
    if parts:
        return "\n".join(parts)
    return strip_tags_preserve_newlines(description_html)


def normalize_feature_name(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip()).lower()


def match_feature_trace(feature_trace_map: Dict[str, str], feature_name: str) -> str:
    normalized = normalize_feature_name(feature_name)
    if not normalized:
        return ""
    if normalized in feature_trace_map:
        return feature_trace_map[normalized]
    for key, trace in feature_trace_map.items():
        if normalized in key or key in normalized:
            return trace
    return ""


def load_feature_trace_map(feature_trace_dir: Optional[str]) -> Dict[str, str]:
    if not feature_trace_dir:
        return {}

    candidate = os.path.abspath(feature_trace_dir)
    report_path = candidate
    if os.path.isdir(candidate):
        report_path = os.path.join(candidate, "feature_report.json")
    if not os.path.exists(report_path):
        return {}

    try:
        from droidbot.utils import format_execution_trace_for_llm

        data = json.loads(read_text(report_path))
        if not isinstance(data, list):
            return {}

        trace_map: Dict[str, str] = {}
        for item in data:
            if not isinstance(item, dict):
                continue
            feature_name = item.get("description", "")
            if not isinstance(feature_name, str) or not feature_name.strip():
                continue
            trace_text = format_execution_trace_for_llm(
                item.get("executed_summary"),
                initial_page_description=item.get("initial_page_description"),
                initial_page_brief_description=item.get("initial_page_brief_description"),
                use_brief=False,
            )
            trace_map[normalize_feature_name(feature_name)] = trace_text or "N/A"
        return trace_map
    except Exception:
        return {}


def parse_clean_html(clean_html_path: str, feature_trace_dir: Optional[str] = None) -> List[PropertyRepairInput]:
    content = read_text(clean_html_path)
    clean_html_dir = os.path.dirname(os.path.abspath(clean_html_path))
    bug_report_error_cache: Dict[str, Dict[str, str]] = {}
    feature_trace_map = load_feature_trace_map(feature_trace_dir)

    row_re = re.compile(
        r"<tr\b[^>]*data-property-index=(?P<quote>['\"])(?P<index>.*?)(?P=quote)[^>]*>(?P<body>.*?)</tr>",
        re.DOTALL | re.IGNORECASE,
    )
    td_re = re.compile(r"<td\b[^>]*>(?P<body>.*?)</td>", re.DOTALL | re.IGNORECASE)

    properties: List[PropertyRepairInput] = []
    for row_match in row_re.finditer(content):
        cells = [m.group("body") for m in td_re.finditer(row_match.group("body"))]
        if len(cells) < 7:
            continue

        property_index = strip_tags_preserve_newlines(cells[0])
        property_name = strip_tags_preserve_newlines(cells[1])
        feature_name = strip_tags_preserve_newlines(cells[2])
        feature_trace = match_feature_trace(feature_trace_map, feature_name)
        property_description = parse_description(cells[3])
        property_code = strip_tags_preserve_newlines(cells[4])
        screenshots = select_property_execution_shots(
            parse_shots(cells[5], clean_html_dir),
            property_name,
        )
        execution_step = extract_execution_step_from_screenshots(screenshots)
        bug_report_path = extract_bug_report_href(cells[-1], clean_html_dir) if len(cells) >= 8 else ""
        error_message = ""
        if bug_report_path:
            error_message = load_error_message_from_bug_report(
                bug_report_path,
                property_name,
                execution_step,
                bug_report_error_cache,
            )
        if not error_message and len(cells) >= 9:
            error_message = normalize_failure_report_text(strip_tags_preserve_newlines(cells[6]))

        if not property_name or not property_code:
            continue

        properties.append(
            PropertyRepairInput(
                property_index=property_index,
                property_name=property_name,
                feature_name=feature_name,
                property_description=property_description,
                property_code=property_code,
                screenshots=screenshots,
                error_message=error_message,
                feature_trace=feature_trace,
            )
        )

    return properties


def build_repair_prompt(item: PropertyRepairInput) -> str:
    screenshot_lines = []
    for idx, shot in enumerate(item.screenshots, start=1):
        screenshot_lines.append(f"{idx}. {shot.caption}")
    screenshots_text = "\n".join(screenshot_lines) if screenshot_lines else "No screenshot captions available."
    feature_trace_text = item.feature_trace or "N/A"

    return f"""You are an expert in mobile UI automated testing and property-based testing.

Your task is to analyze a failed property executed by Kea and determine whether the failure is caused by:
1. A real application bug
2. An error in the property itself (e.g., weak precondition, incorrect assumption, fragile assertion)

If and only if the failure is caused by a PROPERTY_ERROR, you must repair the property so that it will not fail in the same incorrect way again, while preserving its bug-detection capability.

======================== INPUTS ========================
You will be given:
1. Property description (Natural Language Description)
A high-level description of what the property is supposed to guarantee.
Feature Name: {item.feature_name or "N/A"}
Property Name: {item.property_name}
Property Index: {item.property_index or "N/A"}
{item.property_description}

2. Property Code
The full property implementation (including precondition, steps, assertions).
```python
{item.property_code}
```

3. Kea Failure Report
This may include:
- Stack trace

{item.error_message}

4. Screenshots
One or more screenshots captured around the failure moment (from precondition to postcondition).
Screenshot captions:
{screenshots_text}

The actual screenshot images are attached separately to this request.

5. Source Feature Trace
This property was inferred from the following feature execution trace. Use it to preserve the original context in which the property was generated, and avoid repairing the property in a way that makes it incompatible with that source feature flow.
{feature_trace_text}

======================== REQUIRED REASONING PROCESS ========================
Step -0 - Infer the Relevant Source Trace Segment
The source feature trace may be much longer than the specific sub-trace that originally gave rise to this property.
Before classifying or repairing, infer the most relevant contiguous segment of the source feature trace that best matches:
- the property's precondition,
- the action(s) in the property body,
- and the intended post-state/assertion.

Rules for this inference:
- Do NOT assume the whole feature trace is the exact source of the property.
- Identify the smallest contiguous trace segment that most plausibly explains how this property was derived.
- Prefer segments whose start state satisfies the property's intended precondition and whose end state matches the intended post-state.
- If the failure screenshot conflicts with the source feature trace, do not immediately rewrite the property to match the screenshot; first determine whether the screenshot reflects a different context from the inferred source trace segment.
- Any repaired property must remain satisfiable on the inferred relevant source trace segment.

Step 1 - Restate the True Intent
In one concise sentence, restate what the property is logically trying to guarantee, using only observable UI behavior (navigation, visibility, state changes). Do NOT introduce new business assumptions.

Step 2 - Classify the Failure (Choose EXACTLY ONE)
REAL_BUG:
- The precondition appears satisfied.
- The test steps are logically correct.
- The assertion fails due to app behavior inconsistent with the intent.

PROPERTY_ERROR:
- The property should not have been checked in this state.
- The precondition is too weak or incorrect.
- The assertion is overly strong, content-dependent, or not robust.
- The selector/locator strategy is fragile but fixable at property level.

If the classification is REAL_BUG:
- Do NOT modify the property.
- Provide explanation.
- Stop.

Only continue to repair if classification is PROPERTY_ERROR.

Step 3 - Identify Root Cause
Specify which category applies (Choose EXACTLY ONE):
- P1: Incorrect precondition
- P2: Incorrect interaction events
- P3: Incorrect postcondition

For the selected cause:
- Cite specific evidence from logs and/or screenshots.
- You can only select one root cause.
- If the cause is P1, compare:
  - s: the inferred source-trace screen/state where the original property precondition is supposed to hold
  - s': the failing screenshot start state where the property was actually executed
- Use this comparison to identify discriminating UI conditions for repairing the precondition.
- In particular, look for:
  - controls/widgets/texts that exist on s but do not exist on s'; these are good candidates to add as positive guards in the precondition
  - controls/widgets/texts that exist on s' but do not exist on s; these are good candidates to add as negative guards in the precondition
- Prefer guards based on stable, visible UI evidence such as text, resource-id-backed widget existence, dialog anchors, or screen anchors.

Step 4 - Repair Strategy (Follow Strict Priority Order)
Apply the minimal modification necessary, following this order:
1. Strengthen or correct the precondition first
- Add screen/activity anchors
- Require existence of key UI elements
- When repairing an incorrect precondition, explicitly derive the new guards from the s vs s' comparison above.
- Prefer adding the smallest set of discriminating guards that would accept s and reject s'.
- Example repair pattern:
  - if a key widget exists on s but not on s', add `... and self.d(...).exists`
  - if a key widget exists on s' but not on s, add `... and not self.d(...).exists`

2. Improve step robustness if needed
- Verify dialog presence before interaction
- Ensure navigation completed before assertion
- If the root cause is P2 (Incorrect interaction events), repair the action sequence itself.
- Keep the interaction repair minimal: only change the wrong action, missing action, target widget, or ordering needed to realign the property with the inferred source trace segment and intended UI behavior.
- Do NOT convert an interaction-event problem into a precondition or postcondition change unless the evidence clearly shows the events are already correct.

3. Relax or stabilize assertion only if unavoidable
- Avoid business data assumptions
- Prefer structural UI signals
- Avoid brittle text-only anchors unless clearly stable in screenshots
- When repairing an overly strong postcondition, preserve the smallest core observable state change that captures the original intent.
- Prefer removing unsupported extra assertions over replacing them with a new, more specific UI assertion.
- Do NOT replace the original assertion with a different UI-specific outcome unless that new outcome is supported by both the inferred source trace segment and the failure evidence.
- If the original intent is a general state transition (for example, a control disappears and content is revealed), keep that general transition and remove only the over-specific trailing checks.

======================== HARD CONSTRAINTS ========================
- Do NOT introduce new business assumptions not stated in the intent.
- Do NOT make the precondition always false.
- Any strengthened guard must be grounded in visible evidence from logs or screenshots.
- Do NOT significantly reduce the property's ability to detect real bugs.
- Preserve the original coding style and testing framework.
- Do NOT invent non-existing APIs.
- If a helper function is required, implement it explicitly.
- The patched property description must describe an observable and verifiable UI behavior that can be executed and checked with UI automation frameworks such as uiautomator2.
- Do NOT base the patched property description or repaired assertion on unreliable widget-state attributes such as selected / checked / focused / activated / enabled / clickable / checkable.
- Prefer visible on-screen evidence: element exists or disappears, text appears or disappears, text equals or contains a value, dialog/screen opens or closes, or element count changes.
- Prefer the least committal assertion that still preserves bug-detection capability and remains consistent with both the inferred source trace segment and the failure evidence.
- Do NOT introduce a new concrete UI assertion if simply deleting an over-strong assertion is sufficient to repair the property.

Repair Principle:
- Prefer single-location modification.
- If the failure can be fixed by strengthening the precondition, do not change any other part of the property.
- The repaired property must remain compatible with the inferred relevant source trace segment.
- Do NOT produce a repair that invalidates the context in which the property was originally inferred.
- If your repair would make the property unsatisfied on the inferred source trace segment, that repair is invalid.

======================== REQUIRED OUTPUT FORMAT ========================
Strictly follow this exact structure:

Relevant Source Trace Segment:
<quote or summarize the specific source trace states/actions you infer this property came from>

Intent Restatement: <one sentence>
Classification: REAL_BUG / PROPERTY_ERROR
Evidence: <concrete evidence from logs/screenshots>

If classification is REAL_BUG, output:
Next Actions: <recommendations, no code modification>

If classification is PROPERTY_ERROR, output:
Root Causes:
- Px: explanation + evidence
Source Trace Compatibility Check:
- Patched precondition still matches inferred source trace start state: YES / NO
- Patched assertion still matches inferred source trace end state: YES / NO
Minimal Core Behavior Preserved:
<explain what minimal observable state transition from the original property is being preserved>
Patched Property Description:
<describe only the repaired part; do not alter unrelated behavior; it must be directly observable and verifiable from UI behavior>
Patched Property Code:
```python
<full repaired property code>
```

If either source trace compatibility answer is NO, do not output patched code.
Do not output patched code unless Classification is PROPERTY_ERROR.
"""


def code_html(text: str) -> str:
    if not text:
        return "<div class='muted'>N/A</div>"
    return f"<pre><code>{html.escape(text)}</code></pre>"


def prose_html(text: str) -> str:
    if not text:
        return "<div class='muted'>N/A</div>"
    return f"<pre class='prose'>{html.escape(text)}</pre>"


class PropertyRepairer:
    def __init__(self, enable_llm: bool):
        self.enable_llm = enable_llm
        self._llm_client = None

    def _get_llm_client(self):
        if self._llm_client is None:
            from droidbot.llm_client import LLMClient

            self._llm_client = LLMClient()
        return self._llm_client

    def repair(self, item: PropertyRepairInput) -> PropertyRepairResult:
        prompt = build_repair_prompt(item)
        prompt_preview = prompt[:500]

        if not prompt.strip():
            return PropertyRepairResult(
                property_name=item.property_name,
                property_index=item.property_index,
                status="prompt_not_implemented",
                classification="",
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                intent_restatement="",
                evidence="",
                next_actions="",
                root_causes="",
                minimal_core_behavior="",
                patched_description="",
                fixed_code="",
                raw_response="",
                prompt_preview=prompt_preview,
                error="build_repair_prompt() returned an empty prompt.",
            )

        if not self.enable_llm:
            return PropertyRepairResult(
                property_name=item.property_name,
                property_index=item.property_index,
                status="dry_run",
                classification="",
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                intent_restatement="",
                evidence="",
                next_actions="",
                root_causes="",
                minimal_core_behavior="",
                patched_description="",
                fixed_code="",
                raw_response="",
                prompt_preview=prompt_preview,
            )

        try:
            image_paths = [shot.image_path for shot in item.screenshots if os.path.exists(shot.image_path)]
            response, usage = self._get_llm_client().call(prompt, image_paths, include_usage=True)
            usage = usage or {}
            prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
            completion_tokens = int(usage.get("completion_tokens", 0) or 0)
            classification = extract_classification_from_response(response)
            fixed_code = extract_patched_code_from_response(response) if classification == "PROPERTY_ERROR" else ""
            intent_restatement = extract_line_field(response, "Intent Restatement")
            evidence = extract_block_field(
                response,
                "Evidence",
                ["Next Actions", "Root Causes", "Patched Property Description", "Patched Property Code"],
            )
            next_actions = extract_block_field(
                response,
                "Next Actions",
                ["Root Causes", "Patched Property Description", "Patched Property Code"],
            )
            root_causes = extract_block_field(
                response,
                "Root Causes",
                ["Source Trace Compatibility Check", "Minimal Core Behavior Preserved", "Patched Property Description", "Patched Property Code"],
            )
            minimal_core_behavior = extract_block_field(
                response,
                "Minimal Core Behavior Preserved",
                ["Patched Property Description", "Patched Property Code"],
            )
            patched_description = extract_block_field(
                response,
                "Patched Property Description",
                ["Patched Property Code"],
            )
            if classification == "PROPERTY_ERROR":
                status = "ok" if fixed_code else "missing_patched_code"
            elif classification:
                status = classification.lower()
            else:
                status = "unparsed_response"
            return PropertyRepairResult(
                property_name=item.property_name,
                property_index=item.property_index,
                status=status,
                classification=classification,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                intent_restatement=intent_restatement,
                evidence=evidence,
                next_actions=next_actions,
                root_causes=root_causes,
                minimal_core_behavior=minimal_core_behavior,
                patched_description=patched_description,
                fixed_code=fixed_code,
                raw_response=response,
                prompt_preview=prompt_preview,
            )
        except Exception as exc:
            return PropertyRepairResult(
                property_name=item.property_name,
                property_index=item.property_index,
                status="llm_error",
                classification="",
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                intent_restatement="",
                evidence="",
                next_actions="",
                root_causes="",
                minimal_core_behavior="",
                patched_description="",
                fixed_code="",
                raw_response="",
                prompt_preview=prompt_preview,
                error=str(exc),
            )


def dump_inputs(items: List[PropertyRepairInput], output_dir: str, output_suffix: str) -> None:
    payload = []
    for item in items:
        data = asdict(item)
        payload.append(data)
    write_text(
        os.path.join(output_dir, f"repair_inputs_{output_suffix}.json"),
        json.dumps(payload, ensure_ascii=False, indent=2),
    )


def dump_results(results: List[PropertyRepairResult], output_dir: str, output_suffix: str) -> None:
    write_text(
        os.path.join(output_dir, f"repair_results_{output_suffix}.json"),
        json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=2),
    )

    snippets_dir = os.path.join(output_dir, f"fixed_properties_{output_suffix}")
    os.makedirs(snippets_dir, exist_ok=True)
    for result in results:
        if not result.fixed_code.strip():
            continue
        filename = sanitize_filename(result.property_name) + ".py"
        write_text(os.path.join(snippets_dir, filename), result.fixed_code.rstrip() + "\n")


def write_html_report(
    items: List[PropertyRepairInput],
    results: List[PropertyRepairResult],
    output_dir: str,
    output_suffix: str,
) -> None:
    items_by_key = {(item.property_name, item.property_index): item for item in items}

    def rel(path: str) -> str:
        try:
            return os.path.relpath(path, output_dir)
        except Exception:
            return path

    cards: List[str] = []
    for result in results:
        key = (result.property_name, result.property_index)
        item = items_by_key.get(key)
        if item is None:
            continue

        shots_html = []
        for shot in item.screenshots:
            if os.path.exists(shot.image_path):
                img_ref = rel(shot.image_path)
                image = f"<a href='{html.escape(img_ref)}' target='_blank'><img src='{html.escape(img_ref)}' alt='{html.escape(shot.caption)}'/></a>"
            else:
                image = "<div class='muted'>Image missing</div>"
            shots_html.append(
                "<div class='shot'>"
                f"{image}"
                f"<div class='cap'>{html.escape(shot.caption)}</div>"
                "</div>"
            )

        badge_class = {
            "PROPERTY_ERROR": "badge-property",
            "REAL_BUG": "badge-bug",
        }.get(result.classification, "badge-unknown")
        shots_content = "".join(shots_html) if shots_html else "<div class='muted'>No screenshots</div>"

        cards.append(
            "<section class='card'>"
            f"<h2>{html.escape(result.property_name)}</h2>"
            f"<div class='meta'>Property {html.escape(result.property_index or 'N/A')} | Feature: {html.escape(item.feature_name or 'N/A')}</div>"
            f"<div class='badges'><span class='badge {badge_class}'>{html.escape(result.classification or result.status)}</span>"
            f"<span class='badge badge-token'>tokens {result.total_tokens} = {result.prompt_tokens} + {result.completion_tokens}</span></div>"
            "<div class='grid'>"
            "<div>"
            "<h3>Original Description</h3>"
            f"{prose_html(item.property_description)}"
            "<h3>Original Code</h3>"
            f"{code_html(item.property_code)}"
            "<h3>Source Feature Trace</h3>"
            f"{prose_html(item.feature_trace)}"
            "<h3>Failure Report</h3>"
            f"{prose_html(item.error_message)}"
            "</div>"
            "<div>"
            "<h3>Intent Restatement</h3>"
            f"{prose_html(result.intent_restatement)}"
            "<h3>Evidence</h3>"
            f"{prose_html(result.evidence)}"
            "<h3>Next Actions</h3>"
            f"{prose_html(result.next_actions)}"
            "<h3>Root Causes</h3>"
            f"{prose_html(result.root_causes)}"
            "<h3>Minimal Core Behavior Preserved</h3>"
            f"{prose_html(result.minimal_core_behavior)}"
            "<h3>Patched Property Description</h3>"
            f"{prose_html(result.patched_description)}"
            "<h3>Patched Property Code</h3>"
            f"{code_html(result.fixed_code)}"
            "</div>"
            "</div>"
            "<h3>Screenshots</h3>"
            f"<div class='shots'>{shots_content}</div>"
            "<details><summary>Raw LLM Analysis</summary>"
            f"{prose_html(result.raw_response)}"
            "</details>"
            "</section>"
        )

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Property Repair Report</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      margin: 0;
      background: #f4f6fb;
      color: #0f172a;
    }}
    .wrap {{
      max-width: 1600px;
      margin: 0 auto;
      padding: 24px;
    }}
    .card {{
      background: #fff;
      border-radius: 14px;
      box-shadow: 0 10px 30px rgba(15, 23, 42, 0.08);
      padding: 20px;
      margin-bottom: 20px;
    }}
    .meta {{
      color: #475569;
      margin-bottom: 10px;
    }}
    .badges {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-bottom: 16px;
    }}
    .badge {{
      display: inline-block;
      padding: 4px 10px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
    }}
    .badge-property {{ background: #dcfce7; color: #166534; }}
    .badge-bug {{ background: #fee2e2; color: #991b1b; }}
    .badge-unknown {{ background: #e2e8f0; color: #334155; }}
    .badge-token {{ background: #dbeafe; color: #1d4ed8; }}
    .grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 20px;
    }}
    pre {{
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      background: #0f172a;
      color: #e2e8f0;
      padding: 12px;
      border-radius: 10px;
      overflow: auto;
    }}
    .prose {{
      background: #f8fafc;
      color: #0f172a;
      border: 1px solid #e2e8f0;
    }}
    .shots {{
      display: flex;
      gap: 8px;
      overflow-x: auto;
      padding-bottom: 8px;
    }}
    .shot img {{
      width: 220px;
      height: 420px;
      object-fit: contain;
      border: 1px solid #cbd5e1;
      border-radius: 10px;
      background: #fff;
    }}
    .cap {{
      font-size: 12px;
      color: #475569;
      margin-top: 6px;
      max-width: 220px;
    }}
    .muted {{
      color: #64748b;
      font-style: italic;
    }}
    h1, h2, h3 {{
      margin-top: 0;
    }}
    details {{
      margin-top: 16px;
    }}
    @media (max-width: 1000px) {{
      .grid {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Property Repair Report</h1>
    <p>Rows: {len(cards)}</p>
    {''.join(cards) if cards else '<div class="card">No results to display.</div>'}
  </div>
</body>
</html>
"""
    write_text(os.path.join(output_dir, f"repair_report_{output_suffix}.html"), page)


def filter_properties(
    items: List[PropertyRepairInput],
    property_indexes: List[str],
    property_name_contains: Optional[str],
    max_properties: Optional[int],
) -> List[PropertyRepairInput]:
    filtered = items
    if property_indexes:
        allowed = set(property_indexes)
        filtered = [item for item in filtered if item.property_index in allowed]
    if property_name_contains:
        needle = property_name_contains.lower()
        filtered = [item for item in filtered if needle in item.property_name.lower()]
    if max_properties is not None:
        filtered = filtered[:max_properties]
    return filtered


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Parse clean.html and prepare/call LLM to repair false-positive properties."
    )
    parser.add_argument("clean_html", help="Path to clean.html")
    parser.add_argument(
        "--feature-trace-dir",
        default=None,
        help="Path to the feature trace folder (or feature_report.json). The script reads feature_report.json and injects the matched feature execution trace into the prompt.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory to store parsed inputs and repaired property code. Defaults to <clean_html_dir>/property_repairs_<suffix>",
    )
    parser.add_argument(
        "--property-index",
        default=None,
        help="Only process the given property index or comma-separated property indexes, e.g. 6 or 6,82,13.",
    )
    parser.add_argument(
        "--property-name-contains",
        default=None,
        help="Only process properties whose name contains this substring.",
    )
    parser.add_argument(
        "--max-properties",
        type=int,
        default=None,
        help="Only process the first N properties after filtering.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only parse and dump inputs without calling the LLM.",
    )
    args = parser.parse_args()

    clean_html_path = os.path.abspath(args.clean_html)
    property_indexes = parse_property_indexes(args.property_index)
    output_suffix = build_output_suffix(property_indexes)
    output_dir = args.output_dir
    if output_dir is None:
        output_dir = os.path.join(
            os.path.dirname(clean_html_path),
            f"property_repairs_{output_suffix}",
        )
    output_dir = os.path.abspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    items = parse_clean_html(clean_html_path, args.feature_trace_dir)
    items = filter_properties(
        items,
        property_indexes,
        args.property_name_contains,
        args.max_properties,
    )
    dump_inputs(items, output_dir, output_suffix)

    repairer = PropertyRepairer(enable_llm=not args.dry_run)
    results = [repairer.repair(item) for item in items]
    dump_results(results, output_dir, output_suffix)
    write_html_report(items, results, output_dir, output_suffix)

    summary = {
        "clean_html": clean_html_path,
        "output_dir": output_dir,
        "total_properties": len(items),
        "status_counts": {},
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    for result in results:
        summary["status_counts"][result.status] = summary["status_counts"].get(result.status, 0) + 1
        summary["prompt_tokens"] += result.prompt_tokens
        summary["completion_tokens"] += result.completion_tokens
        summary["total_tokens"] += result.total_tokens

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
