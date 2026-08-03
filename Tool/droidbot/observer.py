

import logging
from .utils import merge_two_images, append_llm_output, format_execution_trace_for_llm
from .prompt import judge_feature_status

class Observer:
    def __init__(self, input_policy):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.input_policy = input_policy

    def judge_feature_status(self):
        try:
            new_feature = self.input_policy.active_feature
            annotated_screenshot_path_before = self.input_policy.last_state.generate_annotated_screenshot() if self.input_policy.last_state else None
            screenshot_path_after = self.input_policy.current_state.screenshot_path
            merged_image_path = self.input_policy.current_state.screenshot_path.replace(".png", "_merged.png")
            if annotated_screenshot_path_before:
                merge_two_images(annotated_screenshot_path_before, screenshot_path_after, merged_image_path)
            execution_trace = format_execution_trace_for_llm(
                new_feature.executed_summary,
                initial_page_description=new_feature.initial_page_description,
                use_brief=True,
                initial_page_brief_description=new_feature.initial_page_brief_description,
            )
            prompt = judge_feature_status.substitute(
                feature_description=new_feature.description,
                action=self.input_policy.active_feature.next_event,
                ui_element=new_feature.next_event_widget_index,
                executed_summary=execution_trace
            )
            response = self.input_policy.llm.call(prompt, [merged_image_path] if annotated_screenshot_path_before is not None else [screenshot_path_after])
            raw_response = response
            append_llm_output(stage="judge_feature_status", raw_response=raw_response, output_dir=self.input_policy.device.output_dir, action_count=self.input_policy.action_count)
            parse_response = self.input_policy.llm.parse_judge_feature_status_prompt(response)
            return parse_response
        
        except Exception as e:
            self.logger.error(f"Error in judging feature status: {e}")
            return {"decision": "FAILED",
                    "current_page_description": "",
                    "action_description": ""}
