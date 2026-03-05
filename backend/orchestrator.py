import json
import os
from openai import OpenAI
from dotenv import load_dotenv

from backend.prompts import FINANCE_SYSTEM_PROMPT
from backend.tools import scan_pending_billing, draft_ar_invoice, draft_ap_bill, query_database, FINANCE_TOOLS 

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

AVAILABLE_TOOLS = {
    "scan_pending_billing": scan_pending_billing,
    "draft_ar_invoice": draft_ar_invoice,
    "draft_ap_bill": draft_ap_bill,
    "query_database": query_database
}

CHAT_HISTORY = []

def handle_message(message: str):
    """Generator that yields thoughts in real-time before the final result."""
    global CHAT_HISTORY
    
    yield json.dumps({"type": "thought", "content": "Analyzing request context..."}) + "\n"

    messages = [{"role": "system", "content": FINANCE_SYSTEM_PROMPT}]
    for msg in CHAT_HISTORY[-3:]:
        messages.append(msg)
    messages.append({"role": "user", "content": message})

    max_loops = 5 
    loop_count = 0

    while loop_count < max_loops:
        try:
            response = client.chat.completions.create(
                model="gpt-5.2",
                response_format={ "type": "json_object" },
                messages=messages,
                tools=FINANCE_TOOLS,
                tool_choice="auto",
                temperature=0.9
            )
            
            response_message = response.choices[0].message
            
            if response_message.tool_calls:
                messages.append(response_message)
                for tool_call in response_message.tool_calls:
                    func_name = tool_call.function.name
                    func_args = json.loads(tool_call.function.arguments)
                    
                    # STREAM THE THOUGHT TO THE UI
                    friendly_name = func_name.replace("_", " ").title()
                    yield json.dumps({"type": "thought", "content": f"Running tool: {friendly_name}..."}) + "\n"
                    
                    function_to_call = AVAILABLE_TOOLS.get(func_name)
                    if function_to_call:
                        func_response = function_to_call(**func_args)
                        messages.append({
                            "tool_call_id": tool_call.id,
                            "role": "tool",
                            "name": func_name,
                            "content": json.dumps(func_response),
                        })
                        yield json.dumps({"type": "thought", "content": f"Gathered data from {friendly_name}."}) + "\n"
                        
                loop_count += 1
                continue 

            final_json = json.loads(response_message.content)
            
            CHAT_HISTORY.append({"role": "user", "content": message})
            CHAT_HISTORY.append({"role": "assistant", "content": final_json.get("narration", "")})
            
            # YIELD THE FINAL PAYLOAD
            yield json.dumps({"type": "result", "content": final_json}) + "\n"
            return
            
        except Exception as e:
            print(f"Error: {e}")
            yield json.dumps({"type": "error", "content": str(e)}) + "\n"
            return
            
    yield json.dumps({"type": "error", "content": "Timeout."}) + "\n"