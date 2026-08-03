

def generate_cross_steps_property_prompt(APP_NAME: str, ACTIVITY_LIST: str, feature_description: str, executed_summary: str) -> str:
    prompt = f"""
You are an expert in Android app testing.
Your task is to automatically select MULTIPLE contiguous multi-step segments from the given feature trace, and generate ONE **testable, natural-language property** for EACH selected segment (CROSS-STEP properties).

### App Context
- App name: {APP_NAME}
- Activity list: {ACTIVITY_LIST}

### Feature Context
- Feature description: {feature_description}
- Feature execution trace: {executed_summary}

Each step may include:
- step_id
- prev_page_description
- action_description
- next_page_description (or current_page_description)
- widget_signature (optional)
- result (SUCCESS / FAILED / COMPLETED)

### Segment Selection Requirements (you MUST follow)
You must select a SET of segments, where each segment:
1) Represents a meaningful combined behavior that cannot be expressed as a single-step property, e.g.:
   - state_preservation: values or UI states remain consistent after multiple actions,
   - intermediate_screen: a short sequence leads to a specific intermediate screen with distinctive widgets
2) Avoid unstable/non-deterministic expectations:
   - Do NOT rely on timestamps (e.g., "moments ago"), network-fed content, or ordering-dependent outcomes.
   - Do NOT assert dynamic external data unless the segment itself creates the data (e.g., entered text).
3) Postcondition must be immediately checkable right after the last step of the segment.

### Non-duplication & Redundancy Rules
- Do NOT output two segments with the exact same step_id range.
- Avoid segments that are essentially the same behavior with only wording differences.
- Prefer segments whose postconditions check different UI widgets or different UI changes (different oracle targets).
- Overlapping segments are allowed ONLY if they test clearly different properties (different postconditions/oracles).

### Property Contract (must-hold)
For each property:
If the precondition holds and the interaction_scenario is executed exactly once and in order, the postcondition must immediately hold on the resulting UI state.
If it does not hold, it indicates a potential bug.

### Writing Guidelines
1) Verifiable facts only; no vague phrasing ("user can", "should be able to", "navigates to").
2) Focus on UI widgets and checkable predicates:
   - "exists", "not exists", "text equals", "text contains", "count increases/decreases", "enabled/checked/selected".
3) Abstract specific text/data:
   - For inputs, use variables like "random title text (T)" and "random content text (C)".
   - In postcondition refer to "the entered text" / "the selected item" instead of concrete strings.
4) Precondition must be specific enough to avoid false positives:
   - Use a combination of 2-4 distinctive widget/text checks to identify the starting UI state of the segment.
5) interaction_scenario must include ONLY actions inside the selected segment, in order (no extra steps).

### Output Format (strict JSON)
Requirements:
- Output must be a valid JSON object parseable by python json.loads().
- Do not include Markdown code fences.
- Do not include any explanations outside the JSON.
- Use double quotes for all keys and string values.

"""
    prompt += """Return exactly one JSON object:
{
  "level": "cross_step",
  "properties": [
    {
      "segment_type": "<one of: state_preservation | intermediate_screen | confirm_effect | other>",
      "focus_steps": [<step_id_1>, <step_id_2>, ...],
      "property_description": "<one sentence summary>",
      "precondition": "<concise, checkable UI state before the first step>",
      "interaction_scenario": "<numbered actions for ONLY this segment>",
      "postcondition": "<concise, immediate, checkable UI state after the last step>"
    }
  ]
}
"""
    return prompt


