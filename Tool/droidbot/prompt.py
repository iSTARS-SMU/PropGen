from string import Template


judge_feature_status = Template("""
You are an expert Android QA engineer.
Your job is to evaluate the result of the last action in a mobile app feature execution process.

You are given:
- The feature being explored: $feature_description
- Execution history as a linear trace that alternates between screens and actions:
$executed_summary
(Trace format:
  - S0, S1, ...: screen descriptions in chronological order
  - A1, A2, ...: actions taken between screens
  - action lines may include [SUCCESS] or [FAILED]
  - action lines may also include `| change: ...` to summarize the visible UI difference caused by that action
  - [SUCCESS] means the action meaningfully moved the app toward completing the feature; [FAILED] means it did not make meaningful progress or was irrelevant to the feature
  - the trace ends with the latest known screen)
- The last action $action performed on the UI element labeled with the number $ui_element
- Two screenshots: one BEFORE and one AFTER the last action (from left to right). The numeric tag of each element is at the top-right corner.

---

### Your task

#### 1. Completion check
Compare the feature goal in $feature_description with:
- the current (AFTER) screenshot, and
- the execution history.

Examples:
- For a "create new note" feature:
  - Typing title and content in the editor is **NOT** COMPLETED. It is progress (SUCCESS).
  - Returning to the main notes list and seeing the new note title in the list IS COMPLETED.
- For a "delete file" feature:
  - Opening a delete dialog is progress (SUCCESS).
  - Closing the dialog and seeing the file no longer in the list is COMPLETED.

#### 2. If NOT completed, judge the outcome of the last action
Carefully compare the BEFORE and AFTER screenshots and decide whether the last action **meaningfully progressed the feature**:

- **SUCCESS**:
  - The action produced a visible, relevant change that moves the app closer to the feature goal
    (e.g., opened the required editor/dialog, filled in text, pressed Save/OK, navigated back to a required overview screen).
  - Even if the UI looks similar, if the action clearly matches a necessary step described or implied by $feature_description
    (such as tapping a "Save", "OK", "Confirm", "Delete" button), you may treat it as SUCCESS, as long as it is part of the logical path toward the verifiable end state.

- **FAILED**:
  - The action caused no meaningful progress toward the feature
    (no relevant change, irrelevant navigation, going to clearly wrong settings/help screens, or repeating an action previously marked FAILED without new context).
  - If you believe this action is **not needed** to complete the feature, classify it as FAILED.

---

### Screen Description Requirements (for `current_page_description`)
Write a detailed, test-oriented description of the AFTER screen.
Do NOT only list one or two core widgets. Include all of the following:
1. Screen role/context: what page this appears to be (list/detail/editor/settings/dialog, etc.).
2. Key visible regions: top bar/title, content area, bottom bar/tabs, floating buttons, dialogs/sheets/snackbars.
3. Actionable elements: important buttons/menus/inputs/toggles currently visible and what they likely do.
4. Input/content state: whether text fields contain text, list is empty/non-empty, selected/toggled/expanded state if visually evident.
5. Feedback/result cues: success/error hints, confirmation messages, disabled/enabled controls, validation messages.
Keep it concrete and verifiable from UI evidence.
Do not mention the overlaid element index labels/tags that are artificially added to the screenshot for interaction (e.g., element numbers in corners). App-native numbers visible in the UI (prices, counts, dates, version numbers, phone numbers, etc.) are allowed.

### State Change Requirements (for `state_change_summary`)
Write one short clause describing the visible difference from BEFORE to AFTER.
Focus only on what appeared, disappeared, changed, or stayed effectively the same.
Keep it concrete and verifiable from UI evidence.

### Output Format (strict JSON)
Requirements:
- Output must be a valid JSON object.
- Do not include any Markdown code-block markers (no ```json or ```).
- Do not include any explanations, comments, or extra text outside the JSON.
- All keys and string values must use double quotes.
- The output must be a single JSON object that can be parsed by python json.loads().

Now, generate JSON in the following structure:
{
  "current_page_description": "<detailed description of the current (AFTER) screen following the 5 requirements above>",
  "state_change_summary": "<one short clause describing the visible difference from BEFORE to AFTER>",
  "action_description": "<concise description of what the user did and what visibly happened as a result, do not include the numeric tag>",
  "reason": "<explain why you chose COMPLETED, SUCCESS, or FAILED; explicitly mention whether the screen is verification-ready and what UI evidence you used>",
  "decision": "COMPLETED | SUCCESS | FAILED"
}
""")


generate_next_action_on_feature_prompt_first_step = Template(
    """
You are an expert Android app tester and planner.
Your task is to decide the **next action** to executing a user-facing feature in an Android app.

### Context
Feature description:
$feature_description

Execution history for this feature:
$executed_summary

(The execution history is a linear trace:
- S0, S1, ... are screen descriptions in chronological order
- A1, A2, ... are actions taken between screens
- action lines may include [SUCCESS] or [FAILED]
- action lines may also include `| change: ...` to summarize the visible UI difference caused by that action
- [SUCCESS] means the action meaningfully moved the app toward completing the feature; [FAILED] means it did not make meaningful progress or was irrelevant to the feature
- the trace ends with the latest known screen
This provides the full context of feature progress, navigation flow, and error feedback without repeating the same screen twice.)

You are currently on the **latest screen** described at the end of the execution summary.
The numeric tag of each UI element is located at the top right corner of the element in the screenshot.
I give you the functionality description of some labeled elements on the second screen, which can help you decide the next action:
$labeled_element_descriptions

I provide a image that contains the last screenshot before the last action and the current screenshot after the last action.
- The last action $action performed on the UI element labeled with the number $ui_element, on the last screen.
- Two screenshots: one before and one after the action (the numeric tag of each element is at the top-right corner), from left to right.

You can call the following functions to interact with those labeled elements on the second screenshot to control the smartphone:

### Action DSL
The element_id is the numeric tag assigned to the UI element in the screenshot.
- tap(element_id: int): tap a button or icon
- long_press(element_id: int): long-press an element to trigger context actions
- text(element_id: int, text_input: str): input text into an editable field. If you execute the search action, make sure to input the exact text required by the feature (e.g., the file name from the page description).
- swipe(element_id: int, direction: str): swipe within a scrollable view ("up", "down", "left", "right")
- back(): press the Android system back button, note that you do not need to provide an element_id for this action.

### Your goal
Generate ONE **next action** that aims to finish the feature.
You should:
1. Consider what the user was trying to accomplish (from feature description).
2. Understand where the user currently is (from the latest screen in the execution history and the second screenshot).
3. Avoid repeating previously failed or irrelevant actions (refer to decision and result logs in executed_summary).
4. Choose the most plausible action on the second screenshot to interact with next, note that you should *only* consider UI elements that are labeled on the second screenshot or select the back action.

### Observation Requirements (for `observation`)
Write a detailed description of the current screenshot for planning the next action.
Do NOT only describe the main widget. Include:
1. Current screen role/context.
2. Main visible UI regions and navigation controls.
3. Actionable controls currently available (buttons, list items, menus, input fields, toggles).
4. Current content/form state (filled/empty fields, selected options, list status).
5. Any transient UI (dialog, toast/snackbar, warning/error/success text).
6. One short clause on what changed compared with the previous screenshot.
Use concrete, UI-verifiable wording.
Do not mention the overlaid element index labels/tags that are artificially added to the screenshot for interaction (e.g., element numbers in corners). App-native numbers visible in the UI (prices, counts, dates, version numbers, phone numbers, etc.) are allowed.

### Output Format (strict JSON)
Requirements:
- Output must be a valid JSON object.
- Do not include any Markdown code-block markers (no ```json or ```).
- Do not include any explanations, comments, or extra text outside the JSON.
- All keys and string values must use double quotes.
- The output must be a single JSON object that can be parsed by python json.loads().
Now, generate JSON in the following structure:
{
  "observation": "<detailed current-screen description following the 6 requirements above>",
  "reason": "<explain why you chose this action to execute the feature>",
  "action": "<select the action to proceed with the feature, e.g., tap(1), and back().>",
}
"""
)


generate_next_action_on_feature_prompt_non_first_step = Template(
    """
You are an expert Android app tester and planner.
Your task is to decide the **next action** to executing a user-facing feature in an Android app.

### Context
Feature description:
$feature_description

Execution history for this feature:
$executed_summary

(The execution history is a linear trace:
- S0, S1, ... are screen descriptions in chronological order
- A1, A2, ... are actions taken between screens
- action lines may include [SUCCESS] or [FAILED]
- action lines may also include `| change: ...` to summarize the visible UI difference caused by that action
- [SUCCESS] means the action meaningfully moved the app toward completing the feature; [FAILED] means it did not make meaningful progress or was irrelevant to the feature
- the trace ends with the latest known screen
This provides the full context of feature progress, navigation flow, and error feedback without repeating the same screen twice.)

You are currently on the **latest screen** described at the end of the execution summary.
The numeric tag of each UI element is located at the top right corner of the element in the screenshot.
I give you the functionality description of some labeled elements on the second screen, which can help you decide the next action:
$labeled_element_descriptions

I provide a image that contains the last screenshot before the last action and the current screenshot after the last action.
- The last action $action performed on the UI element labeled with the number $ui_element, on the last screen.
- Two screenshots: one before and one after the action (the numeric tag of each element is at the top-right corner), from left to right.

You can call the following functions to interact with those labeled elements on the second screenshot to control the smartphone:

### Action DSL
The element_id is the numeric tag assigned to the UI element in the screenshot.
- tap(element_id: int): tap a button or icon
- long_press(element_id: int): long-press an element to trigger context actions
- text(element_id: int, text_input: str): input text into an editable field. If you execute the search action, make sure to input the exact text required by the feature (e.g., the file name from the page description).
- swipe(element_id: int, direction: str): swipe within a scrollable view ("up", "down", "left", "right")
- back(): press the Android system back button, note that you do not need to provide an element_id for this action.

### Your goal
Generate ONE **next action** that aims to finish the feature.
You should:
1. Consider what the user was trying to accomplish (from feature description).
2. Understand where the user currently is (from the latest screen in the execution history and the second screenshot).
3. Avoid repeating previously failed or irrelevant actions (refer to decision and result logs in executed_summary).
4. Choose the most plausible action on the second screenshot to interact with next, note that you should *only* consider UI elements that are labeled on the second screenshot or select the back action.

### Output Format (strict JSON)
Requirements:
- Output must be a valid JSON object.
- Do not include any Markdown code-block markers (no ```json or ```).
- Do not include any explanations, comments, or extra text outside the JSON.
- All keys and string values must use double quotes.
- The output must be a single JSON object that can be parsed by python json.loads().
Now, generate JSON in the following structure:
{
  "observation": "<describe what you observe in the screenshot(e.g., key labels, buttons, menus, dialogs). Do not mention the overlaid element index labels/tags that are artificially added to the screenshot for interaction (e.g., element numbers in corners). App-native numbers visible in the UI (prices, counts, dates, version numbers, phone numbers, etc.) are allowed.>",
  "reason": "<explain why you chose this action to execute the feature>",
  "action": "<select the action to proceed with the feature, e.g., tap(1), and back().>",
}
"""
)


generate_property_from_feature_prompt = Template("""
You are an expert in Android app testing.
Your task is to generate one **testable, natural-language property** from the given app feature execution trace.
The property will be used to verify the correctness of the app. I will employ automated testing tools to check whether the property holds in the app under different runs. If the postcondition of the property does not hold after executing the interaction_scenario from a state satisfying the precondition, it indicates a potential bug in the app.

### App Context
- App name: $APP_NAME
- Activity list: $ACTIVITY_LIST

### Feature Context
- Feature description: $feature_description
- Feature execution trace: $executed_summary

The execution trace is a linear screen/action sequence:
- S0, S1, ...: screen descriptions in chronological order
- A1, A2, ...: actions taken between screens
- action lines may include [SUCCESS] or [FAILED]
- action lines may also include `| change: ...` to summarize the visible UI difference caused by that action
- [SUCCESS] means the action meaningfully moved the app toward completing the feature; [FAILED] means it did not make meaningful progress or was irrelevant to the feature

### Reasoning Process
Let me guide you through the reasoning steps to extract a property. Let's think step by step:
1. **Understand the App and Feature**: Review the app context and feature description to grasp the intended functionality.
2. **Analyze the Execution Trace**: Examine each step in the feature execution trace to see how the app's UI changed in response to user actions.
3. **Identify the UI changes**: Look for key UI changes that indicate successful completion of feature steps.
4. **Formulate the Property**: Based on the identified UI changes, draft a property of the app related to the feature.
Structure the property in 3 parts:
   - **precondition**: the condition must be hold before the interaction scenario, e.g., the widget exists or not.
   - **interaction_scenario**: a list descriptions of the user's actions.
   - **postcondition**: the condition must be **immediately** hold after the interaction scenario, e.g., the widget exists or not.
You must be careful that the property must be true for the app under different runs. It means as long as the precondition is satisfied, executing the interaction_scenario should always lead to the postcondition.

### Property Contract (must-hold)
If the **precondition** holds and the **interaction_scenario** is executed exactly once and in order, the **postcondition must immediately hold** on the resulting UI state.
If the postcondition does not hold under these conditions, it indicates a **potential app bug**.

### Writing Guidelines

1. Verifiable facts only; no vague phrasing ("user can", "should be able to", "navigates to").
2. **focus on the UI widgets**:
   - When describing the property, focus on the UI widgets that can be observed on the screen, such as buttons, text, views, etc. You should not check the structual layouts such as dialogs, and use the presence of widgets to indicate the presence of a structural layout. For example, instead of saying "a delete confirmation dialog appears", you can say "delete button exists and cancel button exists", because the presence of these buttons can indicate the presence of the delete confirmation dialog, and it is more verifiable.
   - When writing the property, directly describe the actions or predicates on the UI widgets, e.g., "click the 'Add' button", "the text 'Hello' exists", etc. Do not add extra explanations or interpretations (e.g., in which state).
   - For precondition and postcondition, focus on the key checkable UI widgets that are directly related to the property being described.
   - use precise terms like "exists", "not exists", "click", "text contains", "text equals", "the number of UI widgets" etc.
3. **abstract the specific text**:
    - When referring to specific text in the app (e.g., file names, note titles), use generic widget description like "file name", "note title", etc. For example, instead of "click the text 'my note'", write "click the note title". For example, in the precondition, use "note title exists" instead of "note title 'Grocery List' exists".
    - Avoid using exact strings from the app unless they are standard UI widgets (e.g., "Save", "Delete", "OK").
    - If the property's interaction_scenario involves creating a text item, you can use "random text" or "sample text" to indicate that the content is not specific. Then, if the postcondition involves checking for the presence of the created text item, use "the created text" or "the entered text". Note that you cannot use "random text" in the precondition, as it is not yet created at that point.
4. The property must describe an **observable and verifiable behavior** that a tester could execute and check using UI automation frameworks (such as uiautomator2). Do not use unreliable widget-state attributes as the assertion basis (e.g., selected/checked/focused/activated/enabled/clickable/checkable). Instead, focus on visible evidence on screen, such as whether a button/text exists, text appears or disappears, text equals/contains a value, or count changes.
5. For the precondition, please add sufficient UI widget checks to avoid false positives during automated testing. The precondition should ensure that the app is in the correct state before executing the interaction_scenario. For example, if a precondition is "options button exists", it may lead to false positives as multiple screens may have an "options" button. Instead, you can add more specific checks like "options button exists and 'Settings' exists".
6. For the postcondition, note that:
    - The Feature execution trace is only one trace of the feature, it may not cover all the possible variations of the feature. Therefore, when writing the postcondition, you should focus on the key observable changes that are most likely to hold across different executions of the feature, rather than specific details that may vary. For example, if the execution trace shows that after creating a new note, the note title appears in the notes list, you can write the postcondition as "the created note title exists in the notes list" instead of "the note title 'Grocery List' exists in the notes list". This way, the property is more general and can be applied to different runs of the app with different note titles.
### Example
Use these as a reference for your output format and style:
1. Feature: "Create a new note"
  Property:
  {
    "property_description": "Creating a new note adds it to the notes list.",
    "precondition": "the 'Add Note' button exists and text 'Notes' exists.",
    "interaction_scenario": "1. Tap the 'Add Note' button. 2. Generate random text and enter it in the note editor. 3. Tap the back button.",
    "postcondition": "the random text exists."
  }
2. Feature: "Delete an item from file list"
  Property:
  {
    "property_description": "Deleting an item removes it from the file list.",
    "precondition": "file name exists and option button exists.",
    "interaction_scenario": "1. randomly select a file name. 2. long-click the selected file name. 3. Tap the 'Delete' option . 4. Click 'confirm' button.",
    "postcondition": "the selected file name not exists."
  }
---

### Output Format (strict JSON)
Requirements:
- Output must be a valid JSON object.
- Do not include any Markdown code-block markers (no ```json or ```).
- Do not include any explanations, comments, or extra text outside the JSON.
- All keys and string values must use double quotes.
- The output must be a single JSON object that can be parsed by python json.loads().
Now, generate JSON in the following structure:
{
  "property_description": "<string - one sentence summary of the property>",
  "precondition": "<string - consise description about required UI state before execution (observable and checkable), e.g., element exists or not>",
  "interaction_scenario": "<string - main user actions to perform the feature, split by the numbered steps>",
  "postcondition": "<string - consise description about expected UI state after execution, immediate, deterministic, on-screen outcome that can be asserted, e.g., element exists or not>",
}
""")
