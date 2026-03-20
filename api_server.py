#!/usr/bin/env python3
import os
import sys
import json
from datetime import datetime, timedelta
from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build
from dotenv import load_dotenv
from zoneinfo import ZoneInfo

# Load environment variables
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

app = Flask(__name__)
CORS(app)

CLINIC_TZ = "America/New_York"
CALENDAR_ID = os.getenv('GOOGLE_CALENDAR_ID', 'primary')
CREDENTIALS_FILE = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')

# --- Google Calendar Helper Functions ---

def get_google_service():
    """Initialize Google API service."""
    if not CREDENTIALS_FILE or not os.path.exists(CREDENTIALS_FILE):
        print("❌ GOOGLE_APPLICATION_CREDENTIALS not found or file missing.")
        return None
    try:
        SCOPES = ['https://www.googleapis.com/auth/calendar']
        creds = service_account.Credentials.from_service_account_file(
            CREDENTIALS_FILE, scopes=SCOPES)
        return build('calendar', 'v3', credentials=creds)
    except Exception as e:
        print(f"❌ Error initializing Google service: {e}")
        return None

def list_appointments_logic(limit=10):
    """Fetch upcoming appointments from Google Calendar."""
    service = get_google_service()
    if not service: return []
    try:
        now = datetime.utcnow().isoformat() + 'Z'
        events_result = service.events().list(
            calendarId=CALENDAR_ID, timeMin=now,
            maxResults=limit, singleEvents=True,
            orderBy='startTime').execute()
        return events_result.get('items', [])
    except Exception as e:
        print(f"❌ Error listing appointments: {e}")
        return []

def check_availability_logic(date_str):
    """Check busy slots on a given date (9 AM - 5 PM)."""
    service = get_google_service()
    if not service: return "Error: Calendar service unavailable."
    
    try:
        day_start = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=9, minute=0, second=0)
        day_end = day_start.replace(hour=17, minute=0, second=0)
        
        time_min = day_start.isoformat() + 'Z'
        time_max = day_end.isoformat() + 'Z'

        events_result = service.events().list(
            calendarId=CALENDAR_ID, timeMin=time_min, timeMax=time_max,
            singleEvents=True, orderBy='startTime').execute()
        
        events = events_result.get('items', [])
        if not events:
            return f"The whole day on {date_str} is free (9 AM - 5 PM)."
        
        busy_times = []
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            end = event['end'].get('dateTime', event['end'].get('date'))
            try:
                s_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
                e_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
                busy_times.append(f"{s_dt.strftime('%I:%M %p')} - {e_dt.strftime('%I:%M %p')}")
            except: continue

        return f"Busy times on {date_str}: {', '.join(busy_times)}. Other times (9-5) are free."
    except Exception as e:
        return f"Error checking availability: {str(e)}"

def book_appointment_logic(summary, start_time_iso, duration_minutes=30, description=""):
    """Create a new Google Calendar event."""
    service = get_google_service()
    if not service: return None
    
    try:
        start_dt = datetime.fromisoformat(start_time_iso.replace('Z', '+00:00'))
        end_dt = start_dt + timedelta(minutes=duration_minutes)
        
        event = {
            'summary': summary,
            'description': description,
            'start': {'dateTime': start_dt.isoformat()},
            'end': {'dateTime': end_dt.isoformat()},
        }
        return service.events().insert(calendarId=CALENDAR_ID, body=event).execute()
    except Exception as e:
        print(f"❌ Error booking appointment: {e}")
        return None

# --- Tool Dispatcher for Vapi ---

def route_tool_by_demo_type(demo_type, function_name, args, data):
    """Routes Vapi tool calls to the correct internal logic based on the requested names."""
    print(f"🚀 Dispatching tool: {function_name} for Demo: {demo_type}")
    try:
        # Plumbing-specific function: Scheduling/Booking
        if demo_type == "plumbing" and function_name == "Vertex_Automations_Schedule_Plumbing_Appointment":
            summary = f"[PLUMBING] Appointment: {args.get('name', 'Lead')}"
            event = book_appointment_logic(
                summary=summary, 
                start_time_iso=args.get('dateTime'), 
                description=f"Phone: {args.get('phone', 'N/A')}\nIssue: {args.get('issue', 'Not specified')}"
            )
            if event:
                return f"Plumbing appointment confirmed! Confirmation ID: {event.get('id')}"
            return "Failed to book plumbing appointment. Please try again."

        # Dental-specific function: Availability Check
        elif demo_type == "dental" and function_name == "Vertex_Automations_Check_Dental_Clinic_Availability":
            date_str = args.get("date")
            if not date_str:
                return "Error: No date provided for the dental clinic availability check."
            return check_availability_logic(date_str)
            
        return f"Warning: Function '{function_name}' is not expected for the '{demo_type}' demo."
    except Exception as e:
        print(f"❌ Dispatcher error: {e}")
        return f"Error in dispatcher: {str(e)}"

# --- API Endpoints ---

@app.route('/api/vapi/initiate-call', methods=['POST'])
def initiate_call():
    try:
        data = request.json
        phone_number = data.get('phoneNumber')
        demo_type = data.get('demoType', 'plumbing')
        
        if not phone_number:
            return jsonify({'error': 'Phone number is required'}), 400

        api_key = os.getenv('VAPI_API_KEY')
        assistant_id = {
            'plumbing': os.getenv('VAPI_PLUMBING_ASSISTANT_ID'),
            'dental': os.getenv('VAPI_DENTAL_ASSISTANT_ID'),
        }.get(demo_type) or os.getenv('VAPI_PLUMBING_ASSISTANT_ID')
        
        headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
        payload = {
            'assistantId': assistant_id,
            'phoneNumberId': os.getenv('VAPI_PHONE_NUMBER'),
            'customer': {'number': phone_number},
            'assistantOverrides': {'variableValues': {'name': data.get('name'), 'demoType': demo_type}}
        }
        
        response = requests.post('https://api.vapi.ai/call/phone', json=payload, headers=headers)
        return jsonify(response.json()), response.status_code
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/vapi/calls', methods=['GET'])
def get_vapi_calls():
    """Fetch call logs from Vapi."""
    try:
        limit = request.args.get('limit', 50)
        api_key = os.getenv('VAPI_API_KEY')
        if not api_key:
             return jsonify({'error': 'Missing VAPI_API_KEY'}), 500

        headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
        url = f'https://api.vapi.ai/call?limit={limit}'
        
        # Optionally filter by assistant if set in env
        assistant_id = os.getenv('VAPI_ASSISTANT_ID')
        if assistant_id:
            url += f'&assistantId={assistant_id}'
            
        response = requests.get(url, headers=headers)
        return jsonify(response.json()), response.status_code
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/appointments', methods=['GET'])
def get_appointments():
    """Fetch appointments for the dashboard."""
    try:
        events = list_appointments_logic(int(request.args.get('limit', 10)))
        return jsonify([{
            'id': e['id'], 'summary': e.get('summary', 'Busy'),
            'start': e['start'].get('dateTime', e['start'].get('date')),
            'end': e['end'].get('dateTime', e['end'].get('date')),
            'status': e.get('status', 'confirmed')
        } for e in events])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/vapi/tool/schedule-appointment', methods=['POST'])
def vapi_schedule_appointment():
    try:
        data = request.json or {}
        print(f"📩 Webhook check sequence initiated...")

        # 1. First, check what the demo type is set to from the frontend/Vapi payload
        # Look in the standard places where demoType is stored in a Vapi conversation
        vars = (data.get("variableValues") or 
                data.get("message", {}).get("artifact", {}).get("variableValues") or 
                data.get("assistant", {}).get("variableValues") or 
                data.get("call", {}).get("assistantOverrides", {}).get("variableValues", {}) or
                {})
        demo_type = vars.get("demoType")
        
        if not demo_type:
             print("⚠️ Warning: demoType not detected. Defaulting to 'plumbing'.")
             demo_type = "plumbing"
        
        print(f"✅ Step 1: Demo type identified as '{demo_type}'")

        # 2. Check if a function (tool call) was actually ran/triggered by the agent
        message = data.get("message", {})
        tool_calls = message.get("toolCalls", [])
        
        if not tool_calls:
            print("ℹ️ Step 2: No tool calls found in the message. Exiting.")
            return jsonify({"status": "ignored", "message": "No function was triggered"}), 200

        print(f"✅ Step 2: Found {len(tool_calls)} function(s) triggered.")

        # 3. Proceed to attempt scheduling
        print(f"🚀 Step 3: Attempting to process tools for '{demo_type}' demo...")
        results = []
        for tc in tool_calls:
            try:
                raw_args = tc.get('function', {}).get('arguments', {})
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                
                result_content = route_tool_by_demo_type(demo_type, tc['function']['name'], args, data)
                results.append({
                    "toolCallId": tc['id'], 
                    "result": result_content
                })
            except Exception as inner_e:
                print(f"❌ Error processing individual tool call: {inner_e}")
                results.append({"toolCallId": tc.get('id'), "result": f"Error: {str(inner_e)}"})
                
        return jsonify({"results": results}), 200

    except Exception as e:
        print(f"❌ Webhook Critical Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'message': 'API server is running'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3002))
    print(f"📊 API server running on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
