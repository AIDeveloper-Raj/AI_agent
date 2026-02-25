import json
import os
from openai import OpenAI
from dotenv import load_dotenv

from backend.prompts import FINANCE_SYSTEM_PROMPT
from backend.tools import scan_pending_billing, draft_ar_invoice, draft_ap_bill, FINANCE_TOOLS 

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

AVAILABLE_TOOLS = {
    "scan_pending_billing": scan_pending_billing,
    "draft_ar_invoice": draft_ar_invoice,
    "draft_ap_bill": draft_ap_bill
}

# Add a simple global memory for the POC
CHAT_HISTORY = []

def handle_message(message: str):
    global CHAT_HISTORY
    
    # 1. Build the context with memory
    messages = [{"role": "system", "content": FINANCE_SYSTEM_PROMPT}]
    
    # Inject recent history (last 6 messages to keep context window clean)
    for msg in CHAT_HISTORY[-6:]:
        messages.append(msg)
        
    # Add current message
    messages.append({"role": "user", "content": message})

    max_loops = 5 
    loop_count = 0

    while loop_count < max_loops:
        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                response_format={ "type": "json_object" },
                messages=messages,
                tools=FINANCE_TOOLS,
                tool_choice="auto",
                temperature=0.1
            )
            
            response_message = response.choices[0].message
            
            if response_message.tool_calls:
                messages.append(response_message)
                for tool_call in response_message.tool_calls:
                    func_name = tool_call.function.name
                    func_args = json.loads(tool_call.function.arguments)
                    
                    print(f"🤖 Agent executing: {func_name} with args {func_args}")
                    
                    function_to_call = AVAILABLE_TOOLS.get(func_name)
                    if function_to_call:
                        func_response = function_to_call(**func_args)
                        messages.append({
                            "tool_call_id": tool_call.id,
                            "role": "tool",
                            "name": func_name,
                            "content": json.dumps(func_response),
                        })
                loop_count += 1
                continue 

            final_json = json.loads(response_message.content)
            
            # 2. Save the successful interaction to memory
            CHAT_HISTORY.append({"role": "user", "content": message})
            CHAT_HISTORY.append({"role": "assistant", "content": final_json.get("narration", "")})
            
            return final_json
            
        except Exception as e:
            print(f"Error: {e}")
            return {"intent": "ERROR", "narration": "System error occurred.", "artifacts": {"invoice_drafts": []}}
            
    return {"intent": "ERROR", "narration": "Timeout.", "artifacts": {"invoice_drafts": []}}