import asyncio
from dataclasses import asdict
# from typing import List
import threading

from .device_state import DeviceState
from .feature_agent import FeatureGenerator
from .observer import Observer
from .utils import merge_two_images, append_llm_output, format_execution_trace_for_llm
from .llm_client import LLMClient
from .input_policy import *
import logging
from .input_event import *
from .property import Property, PropertyPool, PropertyStatus
from .feature import Action, FeaturePool, FeatureStatus, Feature, StepLog
import json
import os
import random

GENERATE_POLICY = "property_generate"

MAX_INVALID_ACTIONS = 3

class PropertyGeneratePolicy(InputPolicy):
    def __init__(self, device, app):
        super(PropertyGeneratePolicy, self).__init__(device, app)
        self.logger = logging.getLogger(self.__class__.__name__)
        
        self.llm = LLMClient()

        self.__missed_states = set()
        self.__random_explore = True
        self.__event_trace = ""
        self.__action_history = []
        self.__all_action_history=set()
        self.__num_restarts = 0
        self.__num_steps_outside = 0
        self.explore_mode = True
        self.feature_pool = FeaturePool(path=os.path.join(self.device.output_dir, "feature_report.json"))
        self.property_pool = PropertyPool(path=os.path.join(self.device.output_dir, "property_report.json"))
        self.last_event_flag = ""
        self.explored_activities = set()
        self.exploration_summary = ""
        self.thought = ""
        self.active_feature = None

        self.widget_action_history = {}
        self.number_of_succession_exploration_events = 0
        self.max_succession_exploration_events = 5
        self.known_widgets = set()
        self.widgets_feature_map = {}

        self.observer = Observer(self)
        self.feature_agent = FeatureGenerator(self,self.feature_pool,  self.llm)
        
        self._property_lock = threading.Lock()
    def __update_utg(self):
        self.utg.add_transition(self.last_event, self.last_state, self.current_state) 
    def generate_event(self):
        """
        generate an event
        @return:
        """

        # Get current device state
        # self.current_state = self.device.get_current_state(self.action_count)
        if self.current_state is None:
            import time
            time.sleep(5)
            return KeyEvent(name="BACK")

        event = self.generate_event_based_on_utg()
        self.known_widgets.update(self.current_state.important_widgets)

        self.last_state = self.current_state
        self.last_event = event
        return event

    
    def generate_event_based_on_utg(self):
        """
        generate an event based on current UTG
        @return: InputEvent
        """
        current_state = self.current_state
        # self.__update_utg()
        self.logger.info("Current state: %s" % current_state.state_str)
        if current_state.state_str in self.__missed_states:
            self.__missed_states.remove(current_state.state_str)
        
        # if "com.android.settings" in self.current_state.foreground_activity:
        #     self.logger.info("In settings app, trying to grant permission.")
        # elif "camera" in self.current_state.foreground_activity:
        #     self.logger.info("In camera app, continue.")
        # elif "permission" in self.current_state.foreground_activity.lower():
        #     self.logger.info("In permission granting screen, trying to grant permission.")
        # elif "documentsui" in self.current_state.foreground_activity:
        #     self.logger.info("In file chooser screen, trying to continue.")
        # if "com.android.internal.app.ChooserActivity" in self.current_state.foreground_activity:
        #     self.logger.info("In chooser activity, trying to continue.")
        # elif "com.android.settings" in self.current_state.foreground_activity:
        #     self.logger.info("In settings app, trying to grant permission.")
        if current_state.get_app_activity_depth(self.app) < 0:
            # If the app is not in the activity stack
            start_app_intent = self.app.get_start_intent()
            

            # It seems the app stucks at some state, has been
            # 1) force stopped (START, STOP)
            #    just start the app again by increasing self.__num_restarts
            # 2) started at least once and cannot be started (START)
            #    pass to let viewclient deal with this case
            # 3) nothing
            #    a normal start. clear self.__num_restarts.

            if self.__event_trace.endswith(EVENT_FLAG_START_APP + EVENT_FLAG_STOP_APP) \
                    or self.__event_trace.endswith(EVENT_FLAG_START_APP):
                self.__num_restarts += 1
                self.logger.info("The app had been restarted %d times.", self.__num_restarts)
                self.__event_trace += EVENT_FLAG_START_APP
                self.logger.info("Trying to start the app...")
                self.device.clear_all_apps_from_recent()
                return IntentEvent(intent=start_app_intent)
            else:
                self.__num_restarts = 0

            # pass (START) through
            if not self.__event_trace.endswith(EVENT_FLAG_START_APP):
                if self.__num_restarts > MAX_NUM_RESTARTS:
                    # If the app had been restarted too many times, enter random mode
                    msg = "The app had been restarted too many times. Entering random mode."
                    self.logger.info(msg)
                    self.device.clear_all_apps_from_recent()
                    # self.__random_explore = True
                    return IntentEvent(intent=start_app_intent)
                else:
                    # Start the app
                    self.__event_trace += EVENT_FLAG_START_APP
                    self.logger.info("Trying to start the app...")
                    return IntentEvent(intent=start_app_intent)

        elif current_state.get_app_activity_depth(self.app) > 0:
            # If the app is in activity stack but is not in foreground
            self.__num_steps_outside += 1
            self.logger.info("The app is not in foreground for %d steps.", self.__num_steps_outside)
            if self.__num_steps_outside > MAX_NUM_STEPS_OUTSIDE:
                # If the app has not been in foreground for too long, try to go back
                if self.__num_steps_outside > MAX_NUM_STEPS_OUTSIDE_KILL:
                    self.device.clear_all_apps_from_recent()
                    start_app_intent = self.app.get_start_intent()
                    return IntentEvent(intent=start_app_intent)
                    # stop_app_intent = self.app.get_stop_intent()
                    # go_back_event = IntentEvent(stop_app_intent)
                else:
                    go_back_event = KeyEvent(name="BACK")
                self.__event_trace += EVENT_FLAG_NAVIGATE
                self.logger.info("Going back to the app...")
                return go_back_event
        else:
            # If the app is in foreground
            self.__num_steps_outside = 0
        executed_features = sum(1 for f in self.feature_pool.features if f.status == FeatureStatus.COMPLETED or f.status == FeatureStatus.FAILED)
        total_features = len(self.feature_pool.features)
        self.logger.info(f"Feature execution progress: {executed_features} / {total_features} executed.")

        self.explored_activities.add(current_state.foreground_activity.split('.')[-1])
        if self.active_feature and  self.active_feature.status == FeatureStatus.IN_PROGRESS:
            if self.active_feature.execution_steps >= self.active_feature.max_execution_steps:
                self.logger.info(f"Feature {self.active_feature.description} reached max steps, rejecting.")
                self.active_feature.status = FeatureStatus.FAILED
                self.active_feature = None
                return None
            self.active_feature.execution_steps += 1
            return self._continue_feature()

        if not self.active_feature or self.active_feature.status != FeatureStatus.IN_PROGRESS:
            self.logger.info("Exploring for new feature...")
            self.number_of_succession_exploration_events = 0
            
            next_feature = self.find_next_feature()
            if next_feature:
                self.active_feature = next_feature
                self.save_widget_signature_for_state(first_state_in_property=True, feature=self.active_feature)
                self.logger.info(f"Starting to explore feature: {self.active_feature.description}")
                self.active_feature.start_execution()
                action = self._generate_next_action_for_feature()
                return action
            
            if not self.active_feature:
                self.logger.info("No new features found, generating random event to explore app.")
                possibile_events = []
                possibile_events = current_state.get_possible_input()
                possibile_events.append(KeyEvent(name="BACK"))
                return random.choice(possibile_events)

        if self.__random_explore:
            self.logger.info("Trying random event...")
            action = random.choice(current_state.get_possible_input().append(KeyEvent(name="BACK")))
            # self.__action_history.append(current_state.get_action_desc(action))
            # self.__all_action_history.add(current_state.get_action_desc(action))
            return action

        # If couldn't find a exploration target, stop the app
        stop_app_intent = self.app.get_stop_intent()
        self.logger.info("Cannot find an exploration target. Trying to restart app...")
        self.__action_history.append('- stop the app')
        self.__all_action_history.add('- stop the app')
        self.__event_trace += EVENT_FLAG_STOP_APP
        return IntentEvent(intent=stop_app_intent)
    
    def find_next_feature(self):
        return self.feature_agent.find_next_feature()

    def save_widget_signature_for_state(self, first_state_in_property:bool, feature: Feature):
        widget_signatures = []
        widget_signatures = self.current_state.get_leaf_views_signature_list()
        if first_state_in_property:
            feature.initial_state_views_signatures = widget_signatures
        else:
            feature.final_state_views_signatures = widget_signatures
    
    def _continue_feature(self):
        try:
            self.logger.info("Continuing feature exploration...")

            from concurrent.futures import ThreadPoolExecutor
            new_widgets = [w for w in self.current_state.important_widgets if w not in self.known_widgets]
            generate_new = False
            if len(new_widgets) > 0:
                self.logger.info(f"Found {len(new_widgets)} new important widgets.")
                for w in new_widgets:
                    self.logger.info(f"New important widget: {w}")
                generate_new = True
            with ThreadPoolExecutor(max_workers=2) as executor:
                future_judge = executor.submit(self.observer.judge_feature_status)
                if generate_new:
                    future_generate = executor.submit(self.feature_agent.generate_new_features)              
                
                response = future_judge.result()
                if generate_new:
                    new_features = future_generate.result()
            
            self.add_action_description(response["action_description"])

            if generate_new:
                if new_features:
                    self.logger.info(f"Generated new feature: {len(new_features)}")

            return self._handle_feature_judge_decision(response)
        
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.logger.error(f"Error in continuing feature: {e}")
            return None
    
    def _handle_feature_judge_decision(self, response):
        """
        Handle the LLM judge response for the active feature.
        Returns an InputEvent (action) to execute next or None.
        """
        try:
            decision = response.get("decision")
            # Determine extension
            ext = ".png"
            if self.device.adapters[self.device.minicap]:
                ext = ".jpg"

            prev_screenshot_path = "screen_%s%s" % (self.last_state.tag, ext) if self.last_state else None
            current_screenshot_path = "screen_%s%s" % (self.current_state.tag, ext) if self.current_state else None
            prev_state_views_signatures = self.last_state.get_leaf_views_signature_list() if self.last_state else []
            current_state_views_signatures = self.current_state.get_leaf_views_signature_list() if self.current_state else []

            log = StepLog(
                    step_id=len(self.active_feature.executed_summary) + 1,
                    action_id=self.action_count - 1,
                    prev_page_description=self.active_feature.executed_summary[-1]["next_page_description"]
                    if self.active_feature.executed_summary
                    else self.active_feature.initial_page_description,
                    next_page_description=response["current_page_description"],
                    action_description=response["action_description"],
                    result=decision,
                    next_page_brief_description=(
                        response["current_page_description"] if decision == "COMPLETED" else None
                    ),
                    state_change_summary=response.get("state_change_summary", ""),
                    widget_signature=self.active_feature.next_event_signature,
                    prev_state_views_signatures=prev_state_views_signatures,
                    current_state_views_signatures=current_state_views_signatures,
                    prev_screenshot_path=prev_screenshot_path,
                    current_screenshot_path=current_screenshot_path
                )
            if decision == "COMPLETED":
                self.active_feature.executed_summary.append(asdict(log))
                self.save_widget_signature_for_state(first_state_in_property=False, feature=self.active_feature)
                self.logger.info("LLM judged the property was completed, marking property as COMPLETED.")
                self.active_feature.complete(success=True)
                self.active_feature = None
                self.feature_pool.output_features_to_json()
                return None

            if decision == "SUCCESS":
                self.logger.info("LLM judged the last action was successful, updating feature status.")
                
                self.active_feature.inexecutable_count = 0
                self.active_feature.executed_summary.append(asdict(log))
                action = self._generate_next_action_for_feature()
                if action is None:
                    self.logger.info("Failed to generate next action for feature, marking feature as FAILED.")
                    self.active_feature.complete(success=False)
                    self.active_feature = None
                    return None
                return action

            if decision == "FAILED":
                self.logger.info("LLM judged the last action was FAILED, generating a new action.")
                self.active_feature.executed_summary.append(asdict(log))
                if isinstance(self.active_feature.next_event, UIEvent):
                    self.active_feature.failed_widgets.append(self.active_feature.next_event.view)
                self.active_feature.inexecutable_count += 1
                if self.active_feature.inexecutable_count > self.active_feature.max_inexecutable_count:
                    self.logger.info("Max inexecutable count reached, marking feature as FAILED.")
                    self.active_feature.complete(success=False)
                    self.active_feature = None
                    return None
                action = self._generate_next_action_for_feature()
                if action is None:
                    self.logger.info("Failed to generate next action for feature, marking feature as FAILED.")
                    self.active_feature.complete(success=False)
                    self.active_feature = None
                    return None
                return action

            self.logger.info(f"Unhandled decision '{decision}', no action taken.")
            return None

        except Exception as e:
            self.logger.error(f"Error handling feature judge decision: {e}")
            return None     
        
    def add_action_description(self, action_description: str):
        if isinstance(self.active_feature.next_event, SetTextEvent) or not isinstance(self.active_feature.next_event, UIEvent):
            return
        widget = self.active_feature.next_event.view
        widget["action_description"] = action_description
        self.widget_action_history[widget["view_str"]] = widget

    def _generate_next_action_for_feature(self, retry_warning=""):
        try: 
            self.logger.info("Generating next action for feature...")
            new_feature = self.active_feature
            from .prompt import (
                generate_next_action_on_feature_prompt_first_step,
                generate_next_action_on_feature_prompt_non_first_step,
            )
            annotated_screenshot_path_before = self.last_state.generate_annotated_screenshot() if self.last_state else None
            annotated_screenshot_path_after = self.current_state.generate_annotated_screenshot(failed_widgets=new_feature.failed_widgets)
            
            merged_image_path = self.current_state.annotated_screenshot_path.replace(".png", "_merged.png")
            if annotated_screenshot_path_before:
                merge_two_images(annotated_screenshot_path_before, annotated_screenshot_path_after, merged_image_path)
            widget_descriptions = self.get_widget_description_history()
            execution_trace = format_execution_trace_for_llm(
                new_feature.executed_summary,
                initial_page_description=new_feature.initial_page_description,
                use_brief=True,
                initial_page_brief_description=new_feature.initial_page_brief_description,
            )
            prompt_template = (
                generate_next_action_on_feature_prompt_first_step
                if not new_feature.executed_summary
                else generate_next_action_on_feature_prompt_non_first_step
            )
            prompt = prompt_template.substitute(
                feature_description=new_feature.description,
                executed_summary=execution_trace,
                action=self.active_feature.next_event,
                ui_element=new_feature.next_event_widget_index,
                labeled_element_descriptions=widget_descriptions if widget_descriptions else "N/A"
            )
            response = self.llm.call(prompt, [merged_image_path] if annotated_screenshot_path_before is not None else [annotated_screenshot_path_after])
            raw_response = response
            append_llm_output(stage="generate_next_action", raw_response=raw_response, output_dir=self.device.output_dir, action_count=self.action_count)
            current_page_observation = ""
            try:
                current_page_observation = json.loads(raw_response).get("observation", "")
            except Exception:
                # Keep compatibility with malformed LLM output; downstream parser handles fallback.
                current_page_observation = ""
            response = self.llm.parse_generate_next_action_on_feature_prompt(response)
            if (not self.active_feature.executed_summary
                    and not self.active_feature.initial_page_description
                    and current_page_observation):
                self.active_feature.initial_page_description = current_page_observation
            if (not self.active_feature.executed_summary
                    and not self.active_feature.initial_page_brief_description
                    and current_page_observation):
                self.active_feature.initial_page_brief_description = current_page_observation
            if self.active_feature.executed_summary and current_page_observation:
                self.active_feature.executed_summary[-1]["next_page_brief_description"] = current_page_observation
            act_name = response[0]
            if act_name == "ERROR":
                self.logger.info("LLM failed to generate next action for feature.")
                act_name = "back"
            if act_name == "back":
                action = KeyEvent(name="BACK")
                self.active_feature.next_event_name = act_name
                self.active_feature.next_event_widget_index = None
                self.active_feature.next_event = action
                self.active_feature.next_event_signature = "BACK"
                # self.active_feature.next_event_description = response[-1]
                return action
            action = None
            if response[1] > len(self.current_state.get_actionable_widget_list()):
                self.logger.info("LLM generated an action with an invalid widget index, just back")
                act_name = "back"
                action = KeyEvent(name="BACK")
                self.active_feature.next_event_name = act_name
                self.active_feature.next_event_widget_index = None
                self.active_feature.next_event = action
                self.active_feature.next_event_signature = "BACK"
                # self.active_feature.next_event_description = response[-1]
                return action
            action_class = Action(name=act_name, widget_index=response[1])
            if action_class.widget_index > len(self.current_state.get_actionable_widget_list()):
                self.logger.info("LLM generated an action with an invalid widget index, just back")
                action = KeyEvent(name="BACK")
            if act_name == "text":
                action_class.input_text = response[2]
            elif act_name == "swipe":
                action_class.swipe_direction = response[2]

            action = self.parse_action(action_class)
            widget = action.view
            widget_signature = self.current_state.get_important_view_hash(widget)
            
            self.active_feature.next_event_name = action_class.name
            self.active_feature.next_event_widget_index = action_class.widget_index
            self.active_feature.next_event = action
            self.active_feature.next_event_signature = widget_signature
            # self.active_feature.next_event_description = response[-1]
            return action
        except Exception as e:
            self.logger.error(f"Error in generating next action for feature: {e}")

    def get_widget_description_history(self):
        widget_descriptions = ""
        for index, item in enumerate(self.current_state.get_actionable_widget_list()):
            if item["view_str"] in self.widget_action_history:
                history_widget = self.widget_action_history[item["view_str"]]
                widget_descriptions += f"- label {index+1}: action description: {history_widget['action_description']}\n"
        return widget_descriptions

    def parse_action(self, action_class: Action):
        action = None
        if action_class.name == "tap":
            next_event_widget_index = action_class.widget_index
            act_widget = self.current_state.get_actionable_widget_list()[next_event_widget_index-1]
            action = TouchEvent(view=act_widget)

        elif action_class.name == "text":
            next_event_widget_index = action_class.widget_index
            input_str = action_class.input_text
            act_widget = self.current_state.get_actionable_widget_list()[next_event_widget_index-1]
            action = SetTextEvent(view=act_widget, text=input_str)

        elif action_class.name == "long_press":
            next_event_widget_index = action_class.widget_index
            act_widget = self.current_state.get_actionable_widget_list()[next_event_widget_index-1]
            action = LongTouchEvent(view=act_widget)

        elif action_class.name == "swipe":
            next_event_widget_index = action_class.widget_index
            act_widget = self.current_state.get_actionable_widget_list()[next_event_widget_index-1]
            swipe_dir = action_class.swipe_direction
            action = ScrollEvent(view=act_widget, direction=swipe_dir)
        return action


def generate_properties_from_features(output_dir: str, app_path: str):
    import logging
    logger = logging.getLogger("PropertyGenerator")

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    try:
        from .app import App
        app = App(app_path, output_dir)
        logger.info(f"Loaded app: {app.app_name}")
        
        feature_pool_path = os.path.join(output_dir, "feature_report.json")
        if not os.path.exists(feature_pool_path):
            logger.error(f"Feature report not found at {feature_pool_path}")
            return
        
        feature_pool = FeaturePool(path=feature_pool_path)
        logger.info(f"Loaded {len(feature_pool.features)} features")
        
        completed_features = [f for f in feature_pool.features if f.status == FeatureStatus.COMPLETED]
        
        if not completed_features:
            logger.info("No completed features to generate properties from.")
            return
        
        logger.info(f"Found {len(completed_features)} completed features")
        
        property_pool = PropertyPool(path=os.path.join(output_dir, "property_report.json"))

        llm = LLMClient()

        async def generate_single_property(feature: Feature):
            try:
                logger.info(f"Generating property from feature: {feature.description[:50]}...")
                
                from .prompt import generate_property_from_feature_prompt
                activity_list = ";".join([act.split('.')[-1] for act in app.activities]) if hasattr(app, "activities") else "N/A"
                execution_trace = format_execution_trace_for_llm(
                    feature.executed_summary,
                    initial_page_description=feature.initial_page_description,
                )

                prompt = generate_property_from_feature_prompt.substitute(
                    APP_NAME=app.app_name,
                    ACTIVITY_LIST=activity_list,
                    feature_description=feature.description,
                    executed_summary=execution_trace
                )
                response = await llm.acall_reasoning(prompt)
                res = json.loads(response)
                
                new_property = Property(name=res["property_description"])
                new_property.pre = res["precondition"]
                new_property.interaction = res["interaction_scenario"]
                new_property.post = res["postcondition"]
                new_property.status = PropertyStatus.COMPLETED
                new_property.feature_name = feature.description
                new_property.initial_state_views_signatures = feature.initial_state_views_signatures
                new_property.final_state_views_signatures = feature.final_state_views_signatures
                new_property.widget_signature_list = [
                    item.get("widget_signature", "") 
                    for item in feature.executed_summary 
                    if isinstance(item, dict)
                ]
                state_sequence = []
                if feature.initial_state_views_signatures:
                    state_sequence.append(feature.initial_state_views_signatures)
                for item in feature.executed_summary:
                    if isinstance(item, dict):
                        state_sequence.append(item.get("current_state_views_signatures", []))
                new_property.step_state_views_signatures = state_sequence
                
                # property_pool.add(new_property)
                
                logger.info(f"✓ Generated property: {new_property.name[:60]}...")
                return new_property
                
            except Exception as e:
                logger.error(f"Error generating property for feature '{feature.description[:50]}': {e}")
                return None
        
        async def run_generation_pipeline():
            logger.info(f"Generating properties for {len(completed_features)} features concurrently...")
            
            completed_count = 0
            
            async def generate_with_progress(feature):
                nonlocal completed_count
                res = await generate_single_property(feature)
                if res:
                    completed_count += 1
                    logger.info(f"Progress: {completed_count}/{len(completed_features)} properties generated")
                return res

            tasks = [generate_with_progress(feature) for feature in completed_features]
            results = await asyncio.gather(*tasks)
            
            for prop in results:
                if prop:
                    property_pool.add(prop)

            logger.info(f"✓ Completed generating {completed_count}/{len(completed_features)} properties")
            # Save all properties once at the end
            property_pool.output_properties_to_json()
            
            logger.info(f"Properties saved to: {os.path.join(output_dir, 'property_report.json')}")

            # 2. Generate executable properties
            from .generate_executable_property import generate
            await generate(os.path.join(output_dir, 'property_report.json'), os.path.join(output_dir, "generated_executable_property.json"))

        asyncio.run(run_generation_pipeline())
        
    except Exception as e:
        logger.error(f"Error in property generation: {e}")
        import traceback
        traceback.print_exc()
