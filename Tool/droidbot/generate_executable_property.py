import json
import os
from openai import AsyncOpenAI
from dotenv import load_dotenv
import asyncio

load_dotenv()

def generate_prompt(property_description, ui_element_identifier, step_state_views_signatures):
    template = f"""
You are an expert in Python programming and Android app testing, and your role is to write test snippets for Android apps.

The following APIs are available for test writing:
ui_element: self.d(identifier)
click: ui_element.click()
long click: ui_element.long_click()
rotate device to left: self.d.set_orientation("left")
rotate device to natural: self.d.set_orientation("natural")
back: self.d.press("back")
recent: self.d.press("recent")
edit: ui_element.set_text(text)
exists: ui_element.exists
count: ui_element.count
get text: ui_element.get_text()
scroll the screen to ui element: self.d(scrollable=True).scroll.to(identifier), return true if found, otherwise false
srcoll horizontal: ui_element.scroll.horiz.forward(steps=100)
scroll to right: self.d.swipe_ext("right")  
scroll down to the end: self.d(scrollable=True).scroll.toEnd(steps=100)
relative positioning: 
selects B on the left side of A: A.left(B's identifier)
selects B on the right side of A: A.right(B's identifier)
selects B above A: A.up(B's identifier),
selects B under A: A.down(B's identifier)
children:
selects A's child B: A.child(B's identifier)
siblings:
selects A's sibling B: A.sibling(B's identifier)
send search action to the device: self.d.send_action("search")
open keyboard: self.d.set_fastinput_ime(False)
close keyboard: self.d.set_fastinput_ime(True)
done: self.d(resourceId="com.google.android.inputmethod.latin:id/key_pos_ime_action")
locate a widget which has the text contains string s: self.d(textContains=s)
text equals string s: self.d(text=s)
open notification: self.d.open_notification()
Next button on the notification: self.d(description="Next")
get the current time from the device: self.d(resourceId="com.android.systemui:id/clock").get_text()
generate random string: st.text(alphabet=string.ascii_letters,min_size=1, max_size=10).example()
Note that in the assertion, if you need to check whether the created item exists on the list, you need to use this API: self.d(text=selected_text) or self.d(scrollable=True).scroll.to(text=selected_text). Because the item may not be visible on the screen initially, you need to scroll the list to find it.

Assertion reliability rules (must follow):
1. Do NOT use widget state attributes as assertion evidence, including: selected, checked, focused, focusable, activated, enabled, clickable, checkable, longClickable, scrollable.
2. Do NOT use selectors like self.d(..., selected=True/False) or self.d(..., checked=True/False) in preconditions or assertions.
3. Build assertions only from stable, visible evidence: widget/text exists or not exists, text equals/contains, count changes, or finding text by scrolling.
4. If the property description says "selected", rewrite it into visible outcomes (e.g., a specific text appears, a checkmark label appears, a button text changes, an item count changes).
5. For search flows, after entering text into the search input, you MUST immediately call self.d.send_action("search"). Do not stop at set_text() only.

The app's UI element identifiers are detailed below for reference, ensuring accurate element selection in generating test scripts. Note that you must use these identifiers to write the test snippets, and do not make up any identifiers that are not in the provided UI element identifiers.
the UI element identifiers in the process of interaction, each line is an element identifier in the process, from first to last action:
{ui_element_identifier}

State sequence element identifiers (S0 is initial state, S1..Sn are states after each step):
{step_state_views_signatures}

Important trace alignment note:
- The UI element identifiers in the process and the state sequence identifiers above come from the FULL feature execution trace.
- The current property may be extracted from only a SUBSET of those steps.
- Before writing code, align the property's interaction_scenario with the relevant steps/substates, and only use identifiers that are consistent with that subset.

Here is an example test snippet that you might write, based on a given property description:

Example 1: 

Property description:
Precondition: text "Edit Tags" exists and search button exists
Function body:
1. randomly select a tag
2. get the text of the selected tag as tag name
3. click the delete button on the right of the selected tag
4. assert the selected tag name not exists

Property test snippet:
@prob(0.5)
@precondition(lambda self: self.d(text="Edit Tags").exists and self.d(resourceId="com.automattic.simplenote:id/menu_search").exists)
def test_delete_tag(self):
    tag_count = self.d(resourceId="com.automattic.simplenote:id/tag_name").count
    selected_tag_index = random.randint(0, tag_count - 1)
    selected_tag = self.d(resourceId="com.automattic.simplenote:id/tag_name")[selected_tag_index]
    selected_tag_name = selected_tag.get_text()
    selected_tag.right(resourceId="com.automattic.simplenote:id/tag_trash").click()
    assert not self.d(text="selected_tag_name").exists 

Example 2: 

Property description:
Precondition: text "All Notes" exists and fab button exists
Function body:
1. randomly select a note content
2. get the text of the note content
3. select the note title above the selected note content
4. get the text of the selected note title
5. click the note title
6. click the options button
7. click back
8. assert the text of note title exists

Property test snippet:
@prob(0.5)
@precondition(lambda self: self.d(text="All Notes").exists and self.d(resourceId="com.automattic.simplenote:id/fab_button").exists)
def test_note_title_and_content(self):
    note_content_list = [self.d(resourceId="com.automattic.simplenote:id/note_content")[i] for i in range(self.d(resourceId="com.automattic.simplenote:id/note_content").count)]
    note_content = random.choice(note_content_list)
    note_content_text = note_content.get_text()
    note_title = note_content.up(resourceId="com.automattic.simplenote:id/note_title")
    note_title_text = note_title.get_text()
    note_title.click()
    self.d(description="More options").click()
    self.d.press("back")
    assert self.d(text=note_title_text).exists() or self.d(scrollable=True).scroll.to(text=note_title_text)

Example 3:
Property description:
Precondition: text "All Notes" exists and fab button exists
Function body:
1. click the fab button
2. create a new note with sample title and content
3. click the back button
4. assert the text of the created note title exists

Property test snippet:
@prob(0.5)
@precondition(lambda self: self.d(text="All Notes").exists and self.d(resourceId="com.automattic.simplenote:id/fab_button").exists)
def test_create_note(self):
    self.d(resourceId="com.automattic.simplenote:id/fab_button").click()
    sample_title = st.text(alphabet=string.ascii_letters,min_size=1, max_size=10).example()
    sample_content = st.text(alphabet=string.ascii_letters,min_size=1, max_size=20).example()
    self.d(resourceId="com.automattic.simplenote:id/note_title").set_text(sample_title)
    self.d(resourceId="com.automattic.simplenote:id/note_content").set_text(sample_content)
    self.d.press("back")
    assert self.d(text=sample_title).exists() or self.d(scrollable=True).scroll.to(text=sample_title)

Your task:
Using the available APIs, UI element identifiers and following the example format, please write a test snippet for the following property:
{property_description}
When selecting widgets/assertions, prioritize the identifiers from the matched subset steps of this property instead of unrelated steps from the full trace.

Respond only with the Python code snippet, strictly adhering to the given property description. Do not include any explanations, comments, or text outside the code block.
    """
    return template

async def call_llm(prompt,llm="gpt-5.2"):
    try:
        client = None
        model = None
        if llm == "deepseek_fireworks":
            print("calling deepseek")
            client = AsyncOpenAI(api_key=os.environ.get("DEEPSEEK_API_KEY"),base_url=os.environ.get("DEEPSEEK_URL"))
            model = os.environ.get("DEEPSEEK_MODEL")
        else:
            client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
            model=llm
            print(f"calling {llm}")
        completion = await client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ]
        )
        return completion.choices[0].message.content
    except Exception as e:
        print(f"Error: {e}")
        return ""


def clean_generated_code(code):
    """
    Clean up the generated code by removing markdown code fences.
    
    Args:
        code: Raw code string from LLM
        
    Returns:
        Cleaned code string
    """
    if not code:
        return code
    
    # Remove markdown code fences (```python ... ``` or ``` ... ```)
    code = code.strip()
    if code.startswith("```python"):
        code = code[9:]  # Remove ```python
    elif code.startswith("```"):
        code = code[3:]  # Remove ```
    
    if code.endswith("```"):
        code = code[:-3]  # Remove trailing ```
    
    return code.strip()


def format_step_state_identifiers(step_state_identifiers):
    """
    Format state view signatures into a readable text block for prompt.
    Supports:
    1) New format: [state_signatures_list, ...] where index is state index.
    2) Legacy format: [{"step_id":..., "prev_state_views_signatures":[...], "current_state_views_signatures":[...]}, ...]
    """
    if not step_state_identifiers:
        return ""

    # New compact sequence format: each item is a state-signature list.
    if isinstance(step_state_identifiers, list) and (
        len(step_state_identifiers) == 0 or not isinstance(step_state_identifiers[0], dict)
    ):
        lines = []
        for idx, state_item in enumerate(step_state_identifiers):
            if isinstance(state_item, list):
                state_text = " | ".join(str(x) for x in state_item)
            else:
                state_text = str(state_item)
            lines.append(f"S{idx}: {state_text}")
        return "\n".join(lines)

    # Legacy per-step prev/current format.
    lines = []
    for idx, item in enumerate(step_state_identifiers, start=1):
        if not isinstance(item, dict):
            lines.append(f"Step {idx}: {str(item)}")
            continue
        step_id = item.get("step_id", idx)
        prev_state = item.get("prev_state_views_signatures", [])
        current_state = item.get("current_state_views_signatures", [])
        prev_text = " | ".join(prev_state) if isinstance(prev_state, list) else str(prev_state)
        current_text = " | ".join(current_state) if isinstance(current_state, list) else str(current_state)
        lines.append(f"Step {step_id} PREV: {prev_text}")
        lines.append(f"Step {step_id} CURR: {current_text}")
    return "\n".join(lines)


def format_identifier_block(identifiers):
    """
    Format identifier list/string into a stable multiline block.
    """
    if identifiers is None:
        return ""
    if isinstance(identifiers, list):
        return "\n".join(str(x) for x in identifiers)
    return str(identifiers)


async def process_properties(property_descriptions, ui_identifiers, step_state_views_signatures):
    """
    Process a list of property descriptions with the given UI element identifier.
    
    Args:
        property_descriptions: List of property description strings
        ui_identifier: JSON string of UI element identifiers
    
    Returns:
        List of generated test snippets
    """
    tasks = []
    for i, description in enumerate(property_descriptions):
        ui_identifier = ui_identifiers[i] if i < len(ui_identifiers) else ""
        step_state_identifiers = step_state_views_signatures[i] if i < len(step_state_views_signatures) else ""

        
    # for description in property_descriptions:
        # Convert to string to handle potential non-string values
        desc_str = str(description) if description is not None else ""
        if not desc_str or desc_str == "nan":
            continue
            
        print(f"Processing: {desc_str[:100]}...")
        prompt = generate_prompt(
            desc_str,
            format_identifier_block(ui_identifier),
            format_step_state_identifiers(step_state_identifiers)
        )
        # print(prompt)
        tasks.append(call_llm(prompt))
    
    processed_results = await asyncio.gather(*tasks)
    
    # Clean up the generated code
    cleaned_results = [clean_generated_code(code) for code in processed_results]
    
    return cleaned_results


async def generate(property_json_file, output_file):
    """
    Generate executable properties from JSON input files.
    
    Args:
        property_json_file: Path to JSON file containing property descriptions
        ui_identifier_file: Path to JSON file containing UI element identifiers
        output_file: Path to save the generated test snippets
    """
    try:
        # Read property descriptions from JSON file
        if not os.path.exists(property_json_file):
            print(f"Property file not found: {property_json_file}")
            return
        
        with open(property_json_file, "r", encoding="utf-8") as f:
            property_data = json.load(f)
        
        # Parse property descriptions based on format
        property_descriptions = []
        ui_identifiers = []
        step_state_views_signatures = []
        feature_names = []
        if isinstance(property_data, list):
            # Check if list contains objects with pre/interaction/post structure
            if property_data and isinstance(property_data[0], dict) and 'pre' in property_data[0]:
                # Format from property_report.json
                for item in property_data:
                    feature_names.append(item.get('feature_name', ''))
                    pre = item.get('pre', '')
                    interaction = item.get('interaction', '')
                    post = item.get('post', '')
                    ui_identifiers.append(item.get('widget_signature_list', ''))
                    step_state_views_signatures.append(item.get('step_state_views_signatures', ''))
                    # Combine into property description format
                    description = f"Precondition: {pre}\nFunction body:\n{interaction}\nAssertion: {post}"
                    property_descriptions.append(description)
            else:
                # Simple list of strings
                property_descriptions = property_data
        elif isinstance(property_data, dict):
            # If dict, try common keys or use all values
            property_descriptions = property_data.get("properties", 
                                   property_data.get("descriptions", 
                                   list(property_data.values())))
        else:
            print(f"Unsupported property file format. Expected list or dict.")
            return
        
        # Read UI element identifiers
        # if not os.path.exists(ui_identifier_file):
        #     print(f"UI identifier file not found: {ui_identifier_file}")
        #     return
        
        # with open(ui_identifier_file, "r", encoding="utf-8") as f:
        #     ui_config = json.load(f)
    
        # ui_identifier = json.dumps(ui_config, ensure_ascii=False)
        
        print(f"Loaded {len(property_descriptions)} property descriptions")
        # print(f"UI identifier file: {ui_identifier_file}")
        
        # Process all properties
        results = await process_properties(
            property_descriptions,
            ui_identifiers,
            step_state_views_signatures
        )
        
        # Save results to JSON file
        output_data = {
            "property_file": property_json_file,
            "generated_count": len(results),
            "test_snippets": [
                {
                    "feature_name": str(feature_names[i]) if i < len(feature_names) else "",
                    "property_description": str(property_descriptions[i]) if i < len(property_descriptions) else "",
                    "generated_code": results[i]
                }
                for i in range(len(results))
            ]
        }
        
        # Ensure output directory exists
        output_dir = os.path.dirname(output_file)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)
        
        # Save as JSON
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
        
        print(f"Results saved to {output_file}")
        
        # Also save as a readable Python file
        py_output_file = output_file.replace(".json", ".py")
        with open(py_output_file, "w", encoding="utf-8") as f:
            f.write("# Generated Executable Properties\n")
            f.write(f"# Source: {property_json_file}\n")
            # f.write(f"# UI Identifiers: {ui_identifier_file}\n")
            f.write(f"# Generated {len(results)} test snippets\n\n")
            
            for i, snippet in enumerate(output_data["test_snippets"], 1):
                f.write(f" \n#{'='*80}\n")
                f.write(f"# Feature Name: {snippet['feature_name']}\n")
                f.write(f"# Property {i}\n")
                f.write(f"# Description:\n")
                # Write description as comments
                for line in snippet["property_description"].split('\n'):
                    f.write(f"# {line}\n")
                f.write(f"# {'='*80}\n\n")
                f.write(snippet["generated_code"])
                f.write("\n\n")
        
        print(f"Readable Python code saved to {py_output_file}")
        print(f"Generated {len(results)} test snippets")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


# Configuration: specify the JSON files to use
if __name__ == "__main__":
    # Path to JSON file containing property descriptions (list or dict)
    # Supports property_report.json format with 'pre', 'interaction', 'post' fields
    app_name = "omninotes"
    property_json_file = f"output/{app_name}/20251204_105304/property_report.json"

    # Path to JSON file containing UI element identifiers
    # ui_identifier_file = f"output/{app_name}/annotation_{app_name}_final.json"

    # Output file for generated test snippets
    output_file = f"output/{app_name}/20251204_105304/generated_executable_property.json"

    asyncio.run(main(property_json_file, output_file))
