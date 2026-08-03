import logging
import os
from typing import List
from dotenv import load_dotenv
from openai import OpenAI, AsyncOpenAI
import tiktoken
from .utils import encode_image, print_with_color
import json

logger = logging.getLogger("LLMClient")

load_dotenv()

class LLMClient:
    def __init__(self, model=None, temperature=1):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not found in environment or .env file")

        self.client = OpenAI(api_key=api_key)
        self.aclient = AsyncOpenAI(api_key=api_key)
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-5-mini")
        print_with_color(f"Using LLM model: {self.model}", "green")
        self.temperature = temperature

    def call_reasoning(self, prompt: str) -> str:
        response = self.client.responses.create(
            model=self.model,
            input=prompt,
        )
        # print(response.output)

    async def acall_reasoning(self, prompt: str) -> str:
        response = await self.aclient.responses.create(
            model=self.model,
            input=prompt,
        )
        return response.output_text

    def call(self, prompt: str, images: List[str], include_usage: bool = False):
        try:
            content = [{
                "type": "text",
                "text": prompt
            }]
            for img in images:
                base64_img = encode_image(img)
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"}
                })
            #logger.info("tokens: "+ str(len(tiktoken.encoding_for_model("gpt-4o").encode(prompt))))
            response = self.client.chat.completions.create(
                model=self.model,
                temperature=self.temperature,
                messages=[
                    {
                        "role": "user",
                        "content": content
                    }
                ]
            )
            usage = response.usage.to_dict()
            prompt_tokens = usage["prompt_tokens"]
            completion_tokens = usage["completion_tokens"]
            print_with_color(f"Prompt tokens: {prompt_tokens}, Completion tokens: {completion_tokens}", "yellow")
            print_with_color(f"Request cost is "
                             f"${'{0:.5f}'.format(prompt_tokens / 1000000 * 0.25 + completion_tokens / 1000000 * 2)}",
                             "yellow")
            text = response.choices[0].message.content.strip()
            # logger.info(f"LLM response: {text}...")
            if include_usage:
                return text, usage
            return text
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            if include_usage:
                return "", {}
            return ""

    def parse_explore_prompt(self, prompt: str, is_feature: bool = True) -> List[str]:
        import re
        try:
            observation = re.findall(r"Observation: (.*?)$", prompt, re.MULTILINE)[0]
            think = re.findall(r"Thought: (.*?)$", prompt, re.MULTILINE)[0]
            act = re.findall(r"Action: (.*?)$", prompt, re.MULTILINE)[0]
            if is_feature:
                feature = re.findall(r"Feature: (.*?)$", prompt, re.MULTILINE)[0]
            else:
                feature = re.findall(r"Property: (.*?)$", prompt, re.MULTILINE)[0]
            summary = re.findall(r"Summary: (.*?)$", prompt, re.MULTILINE)[0]
            print_with_color("Observation:", "yellow")
            print_with_color(observation, "magenta")
            print_with_color("Thought:", "yellow")
            print_with_color(think, "magenta")
            print_with_color("Action:", "yellow")
            print_with_color(act, "magenta")
            if is_feature:
                print_with_color("Feature:", "yellow")
            else:
                print_with_color("Property:", "yellow")
            print_with_color(feature, "magenta")
            act_name = act.split("(")[0]
            if act_name == "tap":
                area = int(re.findall(r"tap\((.*?)\)", act)[0])
                return [feature, act_name, area, summary]
            elif act_name == "text":
                # text(5, "Hello, world!")
                params = re.findall(r"text\((.*?)\)", act)[0]
                area, input_str = params.split(",", 1)
                area = int(area)
                return [feature, act_name, area, input_str.strip()[1:-1], summary]
            elif act_name == "long_press":
                area = int(re.findall(r"long_press\((.*?)\)", act)[0])
                return [feature, act_name, area, summary]
            elif act_name == "swipe":
                params = re.findall(r"swipe\((.*?)\)", act)[0]
                area, swipe_dir, dist = params.split(",")
                area = int(area)
                swipe_dir = swipe_dir.strip()[1:-1]
                dist = dist.strip()[1:-1]
                return [feature, act_name, area, swipe_dir, dist, summary]
            else:
                print_with_color(f"ERROR: Undefined act {act_name}!", "red")
                return ["ERROR"]

        except Exception as e:
            logger.error(f"Failed to parse LLM output: {e}")
            return ["ERROR"]

    def parse_judge_feature_status_prompt(self, response: str) -> dict:
        try:
            import json
            response_json = json.loads(response)
            action_description = response_json.get("action_description", "")
            decision = response_json.get("decision", "ERROR")
            current_page_description = response_json.get("current_page_description", "")
            state_change_summary = response_json.get("state_change_summary", "")
            reason = response_json.get("reason", "")
            print_with_color("Action_description:", "yellow")
            print_with_color(action_description, "magenta")
            print_with_color("Current_page_description:", "yellow")
            print_with_color(current_page_description, "magenta")
            print_with_color("State_change_summary:", "yellow")
            print_with_color(state_change_summary, "magenta")
            print_with_color("Reason:", "yellow")
            print_with_color(reason, "magenta")
            print_with_color("Decision:", "yellow")
            print_with_color(decision, "magenta")
            return response_json
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            logger.error(f"Failed to parse LLM output: {response}")
            return ["ERROR"]

    def parse_judge_property_status_prompt(self, prompt: str) -> List[str]:
        import re
        try:
            decision = re.findall(r"Decision: (.*?)$", prompt, re.MULTILINE)[0].strip()
            think = re.findall(r"Thought: (.*?)$", prompt, re.MULTILINE)[0]
            # act = re.findall(r"Action: (.*?)$", prompt, re.MULTILINE)[0]
            # feature = re.findall(r"Feature: (.*?)$", prompt, re.MULTILINE)[0]
            # summary = re.findall(r"Summary: (.*?)$", prompt, re.MULTILINE)[0]
            # summary = re.findall(r"Summary: (.*?)$", prompt, re.MULTILINE)[0]
            print_with_color("Decision:", "yellow")
            print_with_color(decision, "magenta")
            print_with_color("Thought:", "yellow")
            print_with_color(think, "magenta")
            # print_with_color("Summary:", "yellow")
            # print_with_color(summary, "magenta")
            if decision == "BACK":
                page_description = re.findall(r"Page_description: (.*?)$", prompt, re.MULTILINE)[0]
                print_with_color("Page_description:", "yellow")
                print_with_color(page_description, "magenta")
                return ["BACK",page_description, "Back to the previous interface"]
            if decision == "COMPLETED":
                page_description = re.findall(r"Page_description: (.*?)$", prompt, re.MULTILINE)[0]
                print_with_color("Page_description:", "yellow")
                print_with_color(page_description, "magenta")
                return [decision, page_description]
            if decision == "NOTEXIST":
                summary = re.findall(r"Summary: (.*?)$", prompt, re.MULTILINE)[0]
                return [decision, summary]
            if decision == "CONTINUE" or decision == "INEXECUTABLE":
                page_description = re.findall(r"Page_description: (.*?)$", prompt, re.MULTILINE)[0]
                print_with_color("Page_description:", "yellow")
                print_with_color(page_description, "magenta")
                act = re.findall(r"Action: (.*?)$", prompt, re.MULTILINE)[0]
                print_with_color("Action:", "yellow")
                print_with_color(act, "magenta")
                act_description = re.findall(r"Action_description: (.*?)$", prompt, re.MULTILINE)[0]
                print_with_color("Action_description:", "yellow")
                print_with_color(act_description, "magenta")
                act_name = act.split("(")[0]
                if act_name == "tap":
                    area = int(re.findall(r"tap\((.*?)\)", act)[0])
                    return [decision, act_name, area, act_description, page_description, act_description]
                elif act_name == "text":
                    # text(5, "Hello, world!")
                    params = re.findall(r"text\((.*?)\)", act)[0]
                    area, input_str = params.split(",", 1)
                    area = int(area)
                    return [decision, act_name, area, input_str.strip()[1:-1], act_description, page_description, act_description]
                elif act_name == "long_press":
                    area = int(re.findall(r"long_press\((.*?)\)", act)[0])
                    return [decision, act_name, area, act_description, page_description, act_description]
                elif act_name == "swipe":
                    params = re.findall(r"swipe\((.*?)\)", act)[0]
                    area, swipe_dir, dist = params.split(",")
                    area = int(area)
                    swipe_dir = swipe_dir.strip()[1:-1]
                    dist = dist.strip()[1:-1]
                    return [decision, act_name, area, swipe_dir, dist, act_description, page_description, act_description]

            return [decision]
        except Exception as e:
            logger.error(f"Failed to parse LLM output: {e}")
            return ["ERROR"]
        
    def parse_explore_app_prompt(self,prompt:str) -> List[str]:
        import re
        try:
            observation = re.findall(r"Observation: (.*?)$", prompt, re.MULTILINE)[0]
            think = re.findall(r"Thought: (.*?)$", prompt, re.MULTILINE)[0]
            decision = re.findall(r"Decision: (.*?)$", prompt, re.MULTILINE)[0]
            
            print_with_color("Observation:", "yellow")
            print_with_color(observation, "magenta")
            print_with_color("Thought:", "yellow")
            print_with_color(think, "magenta")
            print_with_color("Decision:", "yellow")
            print_with_color(decision, "magenta")
            if decision == "STOP_EXPLORATION":
                return ["STOP_EXPLORATION", think]
            
            act = re.findall(r"Action: (.*?)$", prompt, re.MULTILINE)[0]
            print_with_color("Action:", "yellow")
            print_with_color(act, "magenta")
            summary = re.findall(r"Summary: (.*?)$", prompt, re.MULTILINE)[0]
            print_with_color("Summary:", "yellow")
            print_with_color(summary, "magenta")
            act_name = act.split("(")[0]
            if act_name == "tap":
                area = int(re.findall(r"tap\((.*?)\)", act)[0])
                return [decision, act_name, area, summary]
            elif act_name == "text":
                # text(5, "Hello, world!")
                params = re.findall(r"text\((.*?)\)", act)[0]
                area, input_str = params.split(",", 1)
                area = int(area)
                return [decision, act_name, area, input_str.strip()[1:-1], summary]
            elif act_name == "long_press":
                area = int(re.findall(r"long_press\((.*?)\)", act)[0])
                return [decision, act_name, area, summary]
            elif act_name == "swipe":
                params = re.findall(r"swipe\((.*?)\)", act)[0]
                area, swipe_dir, dist = params.split(",")
                area = int(area)
                swipe_dir = swipe_dir.strip()[1:-1]
                dist = dist.strip()[1:-1]
                return [decision, act_name, area, swipe_dir, dist, summary]
            elif act_name == "back":
                return [decision, act_name, summary]
            else:
                print_with_color(f"ERROR: Undefined act {act_name}!", "red")
                return ["ERROR"]

        except Exception as e:
            logger.error(f"Failed to parse LLM output: {e}")
            return ["ERROR"]

    def parse_generate_postcondition_prompt(self, prompt: str) -> List[str]:
        import re
        try:
            observation = re.findall(r"Observation: (.*?)$", prompt, re.MULTILINE)[0]
            think = re.findall(r"Thought: (.*?)$", prompt, re.MULTILINE)[0]
            postcondition = re.findall(r"Postcondition: (.*?)$", prompt, re.MULTILINE)[0]
            
            print_with_color("Observation:", "yellow")
            print_with_color(observation, "magenta")
            print_with_color("Thought:", "yellow")
            print_with_color(think, "magenta")
            print_with_color("Postcondition:", "yellow")
            print_with_color(postcondition, "magenta")
            return [observation, think, postcondition]
        except Exception as e:
            logger.error(f"Failed to parse LLM output: {e}")
            return ["ERROR"]
        
    def parse_feature_generate_prompt(self, prompt: str) -> List[str]:
        import re
        try:
            observation = re.findall(r"Observation: (.*?)$", prompt, re.MULTILINE)[0]
            think = re.findall(r"Thought: (.*?)$", prompt, re.MULTILINE)[0]
            feature = re.findall(r"Feature: (.*?)$", prompt, re.MULTILINE)[0]
            
            print_with_color("Observation:", "yellow")
            print_with_color(observation, "magenta")
            print_with_color("Thought:", "yellow")
            print_with_color(think, "magenta")
            print_with_color("Feature:", "yellow")
            print_with_color(feature, "magenta")
            return [observation, feature]

        except Exception as e:
            logger.error(f"Failed to parse LLM output: {e}")
            return ["ERROR"]
    def parse_prompt_select_next_feature(self, prompt: str) -> int:
        """
        Output format(strict JSON):
        {
            "Observation": "<Describe what you observe in the screenshot(e.g., key labels, buttons, menus, dialogs)>",
            "Thought": "<List the reasoning steps you took to select the next feature>",
            "Selected_feature": <the index (0-based) of the selected feature in the above feature list>
        }
        """
        try:
            import json
            response_json = json.loads(prompt)
            observation = response_json.get("Observation", "")
            thought = response_json.get("Thought", "")
            selected_feature = response_json.get("Selected_feature", -1)
            print_with_color("Observation:", "yellow")
            print_with_color(observation, "magenta")
            print_with_color("Thought:", "yellow")
            print_with_color(thought, "magenta")
            print_with_color("Selected_feature:", "yellow")
            print_with_color(str(selected_feature), "magenta")
            return response_json
        except Exception as e:
            logger.error(f"Failed to parse LLM output: {e}")
            return ["ERROR"]
        
    def parse_feature_generation_prompt(self, prompt: str):
        """
        output format:
         [
        "Observation": <Describe what you observe in the screenshot(e.g., key labels, buttons, menus, dialogs)>,
        "Thought": <List the reasoning steps you took to identify potential features on this screen>
        "Features": [
            {
                "description": "<concise description of the feature (max 20 words)>" 
            },
            ...
        ]
        """
        import json
        try:
            response_json = json.loads(prompt)
            observation = response_json.get("Observation", [])
            thought = response_json.get("Thought", "")
            features = response_json.get("Features", [])
            print_with_color("Observation:", "yellow")
            print_with_color(observation, "magenta")
               
            print_with_color("Thought:", "yellow")
            print_with_color(thought, "magenta")
            print_with_color("Features:", "yellow")
            for feature in features:
                print_with_color(feature['description'], "magenta")
                print_with_color("widget label: " + str(feature['widget_label']), "yellow")
                # print_with_color("postcondition: " + str(feature['postcondition']), "magenta")
            return response_json
        except Exception as e:
            logger.error(f"Failed to parse LLM output: {e}")
            return ["ERROR"]

    def parse_generate_next_action_on_feature_prompt(self,prompt:str):
        """
        output format:
        ### Output Format (strict JSON)
        Return ONLY valid JSON (no markdown or explanations). Example:

        {
        "action": "tap(12)",
        "action_description": "Tap the 'Add' button to create a new note."
        }
        """
        import json
        try:
            response_json = json.loads(prompt)
            observation = response_json.get("observation", "")
            reason = response_json.get("reason", "")
            action = response_json.get("action", "")
            # action_description = response_json.get("action_description", "")
            print_with_color("Observation:", "yellow")
            print_with_color(observation, "magenta")
            print_with_color("Reason:", "yellow")
            print_with_color(reason, "magenta")
            print_with_color("Action:", "yellow")
            print_with_color(action, "magenta")
            # print_with_color("Action_description:", "yellow")
            # print_with_color(action_description, "magenta")
            act_name = action.split("(")[0]
            if act_name == "tap":
                area = int(json.loads(action[action.index("(")+1:action.index(")")]))
                return [act_name, area]
            elif act_name == "text":
                # text(5, "Hello, world!")
                params = action[action.index("(")+1:action.index(")")]
                area, input_str = params.split(",", 1)
                area = int(area)
                return [act_name, area, input_str.strip()[1:-1]]
            elif act_name == "long_press":
                area = int(json.loads(action[action.index("(")+1:action.index(")")]))
                return [act_name, area]
            elif act_name == "swipe":
                params = action[action.index("(")+1:action.index(")")]
                area, swipe_dir, dist = params.split(",")
                area = int(area)
                swipe_dir = swipe_dir.strip()[1:-1]
                dist = dist.strip()[1:-1]
                return [act_name, area, swipe_dir, dist]
            elif act_name == "back":
                return [act_name]
            
            return ["ERROR"]
        except Exception as e:
            logger.error(f"Failed to parse LLM output: {e}")
            return ["ERROR"]

    
