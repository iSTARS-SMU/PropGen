from string import Template    

prompt_select_next_feature = Template("""
You are an expert Android app tester.
Your task is to select the next feature to explore from a list of identified features for a given app.
You should prioritize features based on the following criteria:
1. Features that are main functionality of the app (e.g., Create, Edit, Delete operations).
2. Features that are actionable from the current app state.
3. Features that have high probability to be successfully executed.
                                      
Here are the list of features identified for the app:
$feature_list
                                      
Output format(strict JSON):
Requirements:
    - Output must be a valid JSON object.
    - Do not include any Markdown code-block markers (no ```json or ```).
    - Do not include any explanations, comments, or extra text outside the JSON.
    - All keys and string values must use double quotes.
    - The output must be a JSON object that can be parsed by python json.loads().
The output JSON object must be in the following format:
{
    "Observation": "<Describe what you observe in the screenshot(e.g., key labels, buttons, menus, dialogs)>",
    "Thought": "<List the reasoning steps you took to select the next feature>",
    "Selected_feature": <the index (0-based) of the selected feature in the above feature list>
}
""")