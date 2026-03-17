#!/usr/bin/env python3
import os
import sys
from datetime import datetime, timedelta
from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build
from dotenv import load_dotenv
from zoneinfo import ZoneInfo

# Load environment variables from parent directory
# Load environment variables from parent directory
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))
# Also load from current directory (overrides parent if present)
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

app = Flask(__name__)
CORS(app)  # Enable CORS for React app

CLINIC_TZ = "America/New_York"

@app.route('/api/vapi/initiate-call', methods=['POST'])
def initiate_call():
    try:
        data = request.json
        phone_number = data.get('phoneNumber')
        name = data.get('name', 'Test User')
        procedure_interest = data.get('procedure_interest', 'General')

        variables = data.get('variables', {})

        if not phone_number:
            return jsonify({'error': 'Phone number is required'}), 400

        api_key = os.getenv('VAPI_API_KEY')
        # Resolve assistant ID server-side using demoType — IDs never leave the backend.
        demo_type = data.get('demoType', 'plumbing')
        assistant_id_map = {
            'plumbing': os.getenv('VAPI_PLUMBING_ASSISTANT_ID'),
            'dental':   os.getenv('VAPI_DENTAL_ASSISTANT_ID'),
        }
        assistant_id = assistant_id_map.get(demo_type) or os.getenv('VAPI_PLUMBING_ASSISTANT_ID')
        phone_number_id = os.getenv('VAPI_PHONE_NUMBER')

        if not api_key or not assistant_id or not phone_number_id:
             print(f"Missing Env Vars - API_KEY: {bool(api_key)}, ASSISTANT_ID: {bool(assistant_id)}, PHONE_NUMBER_ID: {bool(phone_number_id)}")
             return jsonify({'error': 'Server misconfiguration: Missing Vapi env vars'}), 500

        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }
        
        payload = {
            'assistantId': assistant_id,
            'phoneNumberId': phone_number_id,
              "customer": {
    "number": phone_number
  },
            "assistantOverrides": {
                "variableValues": {
                    "name": name,
                    'number': phone_number,
                    'plumbing_issue': procedure_interest  # Map 'procedure_interest' from frontend to 'plumbing_issue' for agent
                }
            },
        }

        # Inject context variables if present
        if variables:
            payload['assistantOverrides'] = {
                'variableValues': variables
            }
        
        print(f"Initiating call to {phone_number}...")
        response = requests.post('https://api.vapi.ai/call/phone', json=payload, headers=headers)
        
        print(f"Vapi Response: {response.status_code} - {response.text}")
        
        if response.status_code == 201 or response.status_code == 200:
             return jsonify(response.json()), 200
        else:
             return jsonify({'error': 'Vapi Error', 'details': response.text}), response.status_code
             
    except Exception as e:
        print(f"Error in initiate_call: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/vapi/calls', methods=['GET'])
def get_vapi_calls():
    try:
        limit = request.args.get('limit', 50)
        assistant_id = os.getenv('VAPI_ASSISTANT_ID') # Enforce backend-side filtering

        api_key = os.getenv('VAPI_API_KEY')
        
        if not api_key:
             return jsonify({'error': 'Server misconfiguration: Missing VAPI_API_KEY'}), 500

        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }
        
        url = f'https://api.vapi.ai/call?limit={limit}'
        if assistant_id:
            url += f'&assistantId={assistant_id}'
        
        print(f"Fetching calls from Vapi (limit={limit}, assistantId={assistant_id})...")
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
             return jsonify(response.json()), 200
        else:
             print(f"Vapi Error: {response.text}")
             return jsonify({'error': 'Vapi Error', 'details': response.text}), response.status_code
             
    except Exception as e:
        print(f"Error in get_vapi_calls: {e}")
        return jsonify({'error': str(e)}), 500

CALENDAR_ID = os.getenv('GOOGLE_CALENDAR_ID', 'primary')
CREDENTIALS_FILE = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')

if not CREDENTIALS_FILE:
    print("❌ ERROR: GOOGLE_APPLICATION_CREDENTIALS not found in .env")
    sys.exit(1)

print(f"🔑 Using credentials: {CREDENTIALS_FILE}")
print(f"📅 Calendar ID: {CALENDAR_ID}")

def get_google_service(service_name, version, scopes):
    """Initialize Google API service."""
    creds = service_account.Credentials.from_service_account_file(
        CREDENTIALS_FILE, scopes=scopes)
    return build(service_name, version, credentials=creds)


def check_calendar_availability(date_str):
    """
    Checks for available slots on a given date.
    Returns a string description of availability.
    """
    try:
        SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']
        service = get_google_service('calendar', 'v3', SCOPES)

        # Parse date and set time range for the day (9 AM - 5 PM)
        day_start = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=9, minute=0, second=0)
        day_end = day_start.replace(hour=17, minute=0, second=0)
        
        # Convert to UTC ISO format for Google Calendar
        time_min = day_start.isoformat() + 'Z'
        time_max = day_end.isoformat() + 'Z'

        print(f"🔎 Checking availability for {date_str} ({time_min} to {time_max})...")

        events_result = service.events().list(
            calendarId=CALENDAR_ID, 
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        
        if not events:
            return f"The whole day on {date_str} is legally free! (9 AM - 5 PM)"
        
        busy_times = []
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            end = event['end'].get('dateTime', event['end'].get('date'))
            # Format nicely: 10:00 AM - 11:00 AM
            try:
                s_dt = datetime.fromisoformat(start)
                e_dt = datetime.fromisoformat(end)
                time_str = f"{s_dt.strftime('%I:%M %p')} - {e_dt.strftime('%I:%M %p')}"
                busy_times.append(time_str)
            except:
                continue

        if busy_times:
            return f"The following times are BUSY on {date_str}: {', '.join(busy_times)}. Any other time between 9 AM and 5 PM is free."
        else:
             return f"The whole day on {date_str} is free!"

    except Exception as e:
        print(f"❌ Error checking availability: {e}")
        return "Sorry, I couldn't check the calendar right now."


@app.route('/api/appointments', methods=['GET'])
def get_appointments():
    """Fetch appointments from Google Calendar."""
    try:
        print("📥 Fetching appointments from Google Calendar...")
        SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']
        service = get_google_service('calendar', 'v3', SCOPES)
        
        now = datetime.utcnow().isoformat() + 'Z'  # 'Z' indicates UTC time
        print(f"   Fetching events from {now}...")
        
        events_result = service.events().list(
            calendarId=CALENDAR_ID, timeMin=now,
            maxResults=10, singleEvents=True,
            orderBy='startTime').execute()
        events = events_result.get('items', [])

        formatted_events = []
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            end = event['end'].get('dateTime', event['end'].get('date'))
            
            # Simple formatting
            formatted_event = {
                'id': event['id'],
                'summary': event.get('summary', 'Busy'),
                'description': event.get('description', ''),
                'start': start,
                'end': end,
                'location': event.get('location', ''),
                'status': event.get('status', 'confirmed'),
                'htmlLink': event.get('htmlLink', '')
            }
            formatted_events.append(formatted_event)

        print(f"✅ Returning {len(formatted_events)} appointments")
        return jsonify(formatted_events)

    except Exception as e:
        print(f"❌ Error fetching appointments: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/vapi/tool/schedule-appointment', methods=['POST'])
def vapi_webhook():
    """Handle Vapi tool calls."""
    try:
        data = request.json
        print(f"📩 Vapi Webhook received: {data}")

        # Check if it's a tool call
        if 'message' in data and 'toolCalls' in data['message']:
            tool_calls = data['message']['toolCalls']
            
            results = []
            for tool_call in tool_calls:
                function_name = tool_call['function']['name']
                function_args = tool_call['function']['arguments']
                call_id = tool_call['id']

                print(f"🔧 Tool Call: {function_name} with args {function_args}")

                if function_name == 'check_availability':
                    # Parse arguments
                    import json
                    if isinstance(function_args, str):
                        args = json.loads(function_args)
                    else:
                        args = function_args
                    
                    date_str = args.get('date')
                    if date_str:
                        result_content = check_calendar_availability(date_str)
                    else:
                        result_content = "Error: Please provide a date in YYYY-MM-DD format."
                
                elif function_name == 'Vertex_Automations_Schedule_Appointment':
                    # Parse arguments (they might come as string or dict)
                    import json
                    if isinstance(function_args, str):
                        args = json.loads(function_args)
                    else:
                        args = function_args

                    name = args.get("name")
                    day = args.get("day")
                    time_iso = args.get("time")
                    
                    if not (day and time_iso):
                         result_content = "Error: Missing day or time."
                    else:
                        # Book appointment logic
                        try:
                            SCOPES = ['https://www.googleapis.com/auth/calendar'] # Need write access
                            service = get_google_service('calendar', 'v3', SCOPES)
                            
                            # start_datetime_str = f"{day}T{time_iso}:00"  <-- Removed
                            start_time = datetime.fromisoformat(time_iso)

                            # Vapi sends no timezone → assume Eastern Time
                            if start_time.tzinfo is None:
                                start_time = start_time.replace(tzinfo=ZoneInfo(CLINIC_TZ))

                            end_time = start_time + timedelta(hours=1)
                            
                            # Check for conflicts
                            events_result = service.events().list(
                                calendarId=CALENDAR_ID, 
                                timeMin=start_time.isoformat(),
                                timeMax=end_time.isoformat(),
                                singleEvents=True
                            ).execute()
                            
                            if events_result.get('items', []):
                                result_content = f"Error: The slot {time_iso} on {day} is already booked. Please choose another time."
                                print(f"⚠️ Double booking prevented for {day} {time_iso}")
                            else:
                                event = {
                                    'summary': f"Plumbing Service: {name}",
                                    'description': f"Booked via Vapi Voice Agent. Customer: {name}. Service Type: {args.get('service_type', 'General')}",
                                    'start': {
                                        'dateTime': start_time.isoformat(),
                                        'timeZone': 'America/New_York',
                                    },
                                    'end': {
                                        'dateTime': end_time.isoformat(),
                                        'timeZone': 'America/New_York',
                                    },
                                }
                                
                                created_event = service.events().insert(calendarId=CALENDAR_ID, body=event).execute()
                                result_content = f"Success! Appointment booked for {day} at {time_iso}. Event ID: {created_event.get('id')}"
                                print(f"✅ Event created: {created_event.get('htmlLink')}")

                            # --- Trigger n8n Webhook for Follow-up ---
                            try:
                                n8n_webhook_url = "https://mattwalter2.app.n8n.cloud/webhook-test/663ccdf8-2dc0-4dd2-be3a-058216228b28"
                                # Extract phone from Vapi call object if available
                                call_data = data.get('call', {})
                                customer_data = call_data.get('customer', {})
                                customer_phone = customer_data.get('number', 'Unknown')
                                
                                webhook_payload = {
                                    "event": "appointment_booked",
                                    "name": name,
                                    "phone": customer_phone,
                                    "appointment_date": day,
                                    "appointment_time": time_iso,
                                    "timestamp": datetime.utcnow().isoformat()
                                }
                                print(f"🚀 Triggering n8n webhook: {webhook_payload}")
                                response = requests.post(n8n_webhook_url, json=webhook_payload, timeout=5)
                                print(f"📬 n8n Response: {response.status_code} - {response.text}")
                            except Exception as hook_err:
                                print(f"⚠️ Failed to trigger n8n webhook: {hook_err}")
                            # -----------------------------------------
                            
                        except Exception as cal_err:
                            result_content = f"Failed to book calendar event: {str(cal_err)}"
                            print(f"❌ Calendar Error: {cal_err}")

                    results.append({
                        "toolCallId": call_id,
                        "result": result_content
                    })



            # Return the results to Vapi
            return jsonify({"results": results}), 200

        return jsonify({'status': 'ignored'}), 200

    except Exception as e:
        print(f"❌ Webhook Error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({'status': 'ok', 'message': 'API server is running'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3002))
    print("📊 Ready to serve Google Sheets, Calendar & WhatsApp data\n")
    app.run(host='0.0.0.0', port=port, debug=False)
