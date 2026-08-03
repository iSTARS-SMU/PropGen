
from string import Template    

prompt_feature_gen = Template("""
    You are an expert Android app tester. 
    I want to collect app features from the given app. 
    You need to analyze the current app screen and identify a list of user-facing FEATUREs that a real user might perform on THIS page.
    
    ### Existing knowledge:   
    App info:
    - App name: $app_name
    - Activity List: $activity_list

    Already identified features for this app:
    $existing_features
                              
    ### Task:
    Reasoning step-by-step:
    1. Examine the app context, existing identified features carefully. These can help you understand the app functionality.
    2. Examine the current screen and identify a list of potential features that could be performed starting from THIS page.
    3. Avoid features that have already been identified or functionality equivalent before (from existing knowledge). For multiple similar features on the same screen, only identify the most representative one. For example, there are multiple items that share the same functionality (e.g., multiple files that can be opened.), you only need to identify one feature for this functionality (e.g., "Open a file" instead of "Open file A", "Open file B", etc.). Do not generate multiple features that are essentially the same except for different parameters (e.g., "Open file A", "Open file B", etc. is not good, instead, you can generate one feature "Open a file" with widget label pointing to one of the files on the screenshot).
    4. Prioritize features according to:
    - Features that are main functionality of the app (e.g., Create, Edit, Delete operations).
    - Features that are different from existing features.
    - Features that have high probability to be successfully executed.  
    5. For each identified feature, provide:
    - A concise description of the feature (max 20 words).
    - the widget numeric label on the screenshot that can be used to trigger this feature.
                              
    ### Output(strict JSON)
    Requirements:
    - Output must be a valid JSON object.
    - Do not include any Markdown code-block markers (no ```json or ```).
    - Do not include any explanations, comments, or extra text outside the JSON.
    - All keys and string values must use double quotes.
    - The output must be a JSON object that can be parsed by python json.loads().
    If you identify new features, return a json object in this format:
    {
    "Observation": <Describe what you observe in the screenshot(e.g., key labels, buttons, menus, dialogs)>,
    "Thought": <List the reasoning steps you took to identify potential features on this screen>
    "Features": [
        {
            "description": "<concise description of the feature (max 20 words)>",
            "widget_label": <the numeric label of the widget on the screenshot that can be used to trigger this feature>,        
        },
        ...
    }
    else, if you cannot identify any new features, return:
    {
    "Observation": <Describe what you observe in the screenshot(e.g., key labels, buttons, menus, dialogs)>,
    "Thought": <List the reasoning steps why no new features can be identified on this screen>,
    "Features": []
    }
    """)