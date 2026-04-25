# Predefined apps, actions, and their required parameters
PREDEFINED_ACTIONS = {
    "gmail": {
        "actions": {
            "send_email": {
                "parameters": ["recipient", "subject", "body"],
                "required": ["recipient", "body"]
            },
            "read_email": {
                "parameters": ["query"],
                "required": []
            }
        }
    },
    "calendar": {
        "actions": {
            "create_event": {
                "parameters": ["title", "start_time", "end_time", "attendees"],
                "required": ["title", "start_time"]
            }
        }
    },
    "notion": {
        "actions": {
            "create_page": {
                "parameters": ["title", "content", "parent_page_id"],
                "required": ["title"]
            }
        }
    },
    "control_flow": {
        "actions": {
            "if_else": {
                "parameters": ["condition", "true_actions", "false_actions"],
                "required": ["condition", "true_actions"]
            },
            "for_loop": {
                "parameters": ["iterable", "loop_variable", "loop_actions"],
                "required": ["iterable", "loop_actions"]
            },
            "while_loop": {
                "parameters": ["condition", "loop_actions"],
                "required": ["condition", "loop_actions"]
            }
        }
    }
}
