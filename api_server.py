#!/usr/bin/env python3
import os
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
CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "primary")
CREDENTIALS_FILE = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

print("🔧 Backend booting...")
print(f"📁 GOOGLE_APPLICATION_CREDENTIALS: {CREDENTIALS_FILE}")
print(f"📅 GOOGLE_CALENDAR_ID: {CALENDAR_ID}")
print(f"🌎 CLINIC_TZ: {CLINIC_TZ}")


# -----------------------------
# Google Calendar Helpers
# -----------------------------
def get_google_service():
    print("🔑 get_google_service() called")
    print(f"📁 Checking credentials file: {CREDENTIALS_FILE}")

    if not CREDENTIALS_FILE or not os.path.exists(CREDENTIALS_FILE):
        print("❌ GOOGLE_APPLICATION_CREDENTIALS not found or file missing.")
        return None

    try:
        scopes = ["https://www.googleapis.com/auth/calendar"]
        creds = service_account.Credentials.from_service_account_file(
            CREDENTIALS_FILE,
            scopes=scopes
        )
        service = build("calendar", "v3", credentials=creds)
        print("✅ Google Calendar service initialized successfully")
        return service
    except Exception as e:
        print(f"❌ Error initializing Google service: {e}")
        return None


def list_appointments_logic(limit=10):
    print(f"📥 list_appointments_logic(limit={limit}) called")
    service = get_google_service()
    if not service:
        print("❌ No Google service available")
        return []

    try:
        now = datetime.utcnow().isoformat() + "Z"
        print(f"⏰ Fetching events from now: {now}")

        events_result = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=now,
            maxResults=limit,
            singleEvents=True,
            orderBy="startTime"
        ).execute()

        events = events_result.get("items", [])
        print(f"✅ Retrieved {len(events)} upcoming appointment(s)")
        return events

    except Exception as e:
        print(f"❌ Error listing appointments: {e}")
        return []


def book_appointment_logic(summary, start_time_iso, duration_minutes=60, description=""):
    print("📝 book_appointment_logic() called")
    print(f"   summary={summary}")
    print(f"   start_time_iso={start_time_iso}")
    print(f"   duration_minutes={duration_minutes}")
    print(f"   description={description}")

    service = get_google_service()
    if not service:
        print("❌ No Google service available")
        return None

    try:
        start_dt = datetime.fromisoformat(start_time_iso.replace("Z", "+00:00"))
        end_dt = start_dt + timedelta(minutes=duration_minutes)

        print(f"⏰ Parsed start_dt={start_dt.isoformat()}")
        print(f"⏰ Parsed end_dt={end_dt.isoformat()}")

        event = {
            "summary": summary,
            "description": description,
            "start": {
                "dateTime": start_dt.isoformat(),
                "timeZone": CLINIC_TZ
            },
            "end": {
                "dateTime": end_dt.isoformat(),
                "timeZone": CLINIC_TZ
            },
        }

        print(f"📤 Sending event to Google Calendar:\n{json.dumps(event, indent=2)}")
        created_event = service.events().insert(
            calendarId=CALENDAR_ID,
            body=event
        ).execute()

        print("✅ Calendar event created successfully")
        print(f"   event_id={created_event.get('id')}")
        print(f"   htmlLink={created_event.get('htmlLink')}")
        return created_event

    except Exception as e:
        print(f"❌ Error booking appointment: {e}")
        return None


def resolve_start_time(preferred_date, time_preference):
    """
    Convert preferredDate + timePreference into a timezone-aware datetime.
    preferred_date must be YYYY-MM-DD.
    time_preference can be:
    - morning
    - afternoon
    - evening
    - asap
    - exact time like '10:00 AM'
    - ISO datetime string
    """
    print(f"🧠 resolve_start_time(preferred_date={preferred_date}, time_preference={time_preference}) called")

    try:
        base_date = datetime.strptime(preferred_date, "%Y-%m-%d").date()
        tp_raw = str(time_preference).strip()
        tp = tp_raw.lower()

        print(f"📅 Parsed base_date={base_date}")
        print(f"🕒 Normalized time_preference={tp}")

        # Try ISO first
        try:
            dt = datetime.fromisoformat(tp_raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ZoneInfo(CLINIC_TZ))
            print(f"✅ Resolved ISO datetime -> {dt.isoformat()}")
            return dt
        except Exception:
            pass

        if tp in ["asap", "urgent", "right now"]:
            dt = datetime.combine(base_date, datetime.min.time()).replace(
                hour=9, minute=0, tzinfo=ZoneInfo(CLINIC_TZ)
            )
            print(f"✅ Resolved asap/urgent -> {dt.isoformat()}")
            return dt

        if tp == "morning":
            dt = datetime.combine(base_date, datetime.min.time()).replace(
                hour=9, minute=0, tzinfo=ZoneInfo(CLINIC_TZ)
            )
            print(f"✅ Resolved morning -> {dt.isoformat()}")
            return dt

        if tp == "afternoon":
            dt = datetime.combine(base_date, datetime.min.time()).replace(
                hour=13, minute=0, tzinfo=ZoneInfo(CLINIC_TZ)
            )
            print(f"✅ Resolved afternoon -> {dt.isoformat()}")
            return dt

        if tp == "evening":
            dt = datetime.combine(base_date, datetime.min.time()).replace(
                hour=16, minute=0, tzinfo=ZoneInfo(CLINIC_TZ)
            )
            print(f"✅ Resolved evening -> {dt.isoformat()}")
            return dt

        try:
            parsed_time = datetime.strptime(tp_raw.upper(), "%I:%M %p").time()
            dt = datetime.combine(base_date, parsed_time).replace(
                tzinfo=ZoneInfo(CLINIC_TZ)
            )
            print(f"✅ Resolved explicit time -> {dt.isoformat()}")
            return dt
        except Exception as time_err:
            print(f"❌ Failed parsing explicit time '{tp_raw}': {time_err}")
            return "Error: Unsupported time format. Use 'morning', 'afternoon', 'evening', 'asap', an ISO datetime, or a time like '10:00 AM'."

    except Exception as e:
        print(f"❌ resolve_start_time error: {e}")
        return f"Error resolving appointment time: {str(e)}"


# -----------------------------
# Tool Dispatcher
# -----------------------------
def route_tool_by_demo_type(demo_type, function_name, args, data):
    print("🚀 route_tool_by_demo_type() called")
    print(f"   demo_type={demo_type}")
    print(f"   function_name={function_name}")
    print(f"   args={json.dumps(args, indent=2) if isinstance(args, dict) else args}")

    try:
        # PLUMBING
        if demo_type == "plumbing" and function_name == "Vertex_Automations_Schedule_Plumbing_Appointment":
            print("🪠 Matched plumbing scheduling tool")

            customer_name = args.get("customerName") or args.get("name") or "Lead"
            phone_number = args.get("phoneNumber") or args.get("phone") or "N/A"
            service_address = args.get("serviceAddress") or args.get("address") or "N/A"
            issue_description = args.get("issueDescription") or args.get("issue") or "Not specified"
            preferred_date = args.get("preferredDate")
            time_preference = args.get("timePreference")

            print("📋 Plumbing values:")
            print(f"   customer_name={customer_name}")
            print(f"   phone_number={phone_number}")
            print(f"   service_address={service_address}")
            print(f"   issue_description={issue_description}")
            print(f"   preferred_date={preferred_date}")
            print(f"   time_preference={time_preference}")

            if not preferred_date or not time_preference:
                print("❌ Missing preferredDate or timePreference for plumbing appointment")
                return "Error: Missing preferredDate or timePreference for plumbing appointment."

            start_time_obj = resolve_start_time(preferred_date, time_preference)
            if isinstance(start_time_obj, str) and start_time_obj.startswith("Error"):
                print(f"❌ resolve_start_time returned error: {start_time_obj}")
                return start_time_obj

            summary = f"[PLUMBING] Appointment: {customer_name}"
            description = (
                f"Customer: {customer_name}\n"
                f"Phone: {phone_number}\n"
                f"Address: {service_address}\n"
                f"Issue: {issue_description}"
            )

            event = book_appointment_logic(
                summary=summary,
                start_time_iso=start_time_obj.isoformat(),
                duration_minutes=60,
                description=description
            )

            if event:
                result = (
                    f"Success! Plumbing appointment booked for "
                    f"{start_time_obj.strftime('%A, %B %d, %Y at %I:%M %p')}."
                )
                print(f"✅ Plumbing booking result: {result}")
                return result

            print("❌ Plumbing appointment booking failed")
            return "Failed to book plumbing appointment. Please try again."

        # DENTAL
        elif demo_type == "dental" and function_name == "Vertex_Automations_Schedule_Dental_Appointment":
            print("🦷 Matched dental scheduling tool")

            patient_name = args.get("patientName") or args.get("name") or "Patient"
            phone_number = args.get("phoneNumber") or args.get("phone") or "N/A"
            patient_status = args.get("patientStatus", "unknown")
            appointment_type = args.get("appointmentType") or args.get("procedure") or "General Dental Visit"
            preferred_date = args.get("preferredDate")
            time_preference = args.get("timePreference")
            notes = args.get("notes", "")

            print("📋 Dental values:")
            print(f"   patient_name={patient_name}")
            print(f"   phone_number={phone_number}")
            print(f"   patient_status={patient_status}")
            print(f"   appointment_type={appointment_type}")
            print(f"   preferred_date={preferred_date}")
            print(f"   time_preference={time_preference}")
            print(f"   notes={notes}")

            if not preferred_date or not time_preference:
                print("❌ Missing preferredDate or timePreference for dental appointment")
                return "Error: Missing preferredDate or timePreference for dental appointment."

            start_time_obj = resolve_start_time(preferred_date, time_preference)
            if isinstance(start_time_obj, str) and start_time_obj.startswith("Error"):
                print(f"❌ resolve_start_time returned error: {start_time_obj}")
                return start_time_obj

            summary = f"[DENTAL] Appointment: {patient_name}"
            description = (
                f"Patient: {patient_name}\n"
                f"Phone: {phone_number}\n"
                f"Patient Status: {patient_status}\n"
                f"Appointment Type: {appointment_type}\n"
                f"Notes: {notes}"
            )

            event = book_appointment_logic(
                summary=summary,
                start_time_iso=start_time_obj.isoformat(),
                duration_minutes=60,
                description=description
            )

            if event:
                result = (
                    f"Success! Dental appointment booked for "
                    f"{start_time_obj.strftime('%A, %B %d, %Y at %I:%M %p')}."
                )
                print(f"✅ Dental booking result: {result}")
                return result

            print("❌ Dental appointment booking failed")
            return "Failed to book dental appointment. Please try again."

        warning_msg = f"Warning: Function '{function_name}' is not expected for the '{demo_type}' demo."
        print(f"⚠️ {warning_msg}")
        return warning_msg

    except Exception as e:
        print(f"❌ Dispatcher error: {e}")
        return f"Error in dispatcher: {str(e)}"


# -----------------------------
# API Endpoints
# -----------------------------
@app.route('/api/vapi/initiate-call', methods=['POST'])
def initiate_call():
    try:
        print("📞 /api/vapi/initiate-call called")
        data = request.json or {}
        print(f"📥 Request payload:\n{json.dumps(data, indent=2)}")

        phone_number = data.get("phoneNumber")
        demo_type = data.get("demoType", "plumbing")
        caller_name = data.get("name")

        print(f"   phone_number={phone_number}")
        print(f"   demo_type={demo_type}")
        print(f"   caller_name={caller_name}")

        if not phone_number:
            print("❌ Phone number is missing")
            return jsonify({"error": "Phone number is required"}), 400

        api_key = os.getenv("VAPI_API_KEY")
        assistant_id = {
            "plumbing": os.getenv("VAPI_PLUMBING_ASSISTANT_ID"),
            "dental": os.getenv("VAPI_DENTAL_ASSISTANT_ID"),
        }.get(demo_type) or os.getenv("VAPI_PLUMBING_ASSISTANT_ID")

        phone_number_id = os.getenv("VAPI_PHONE_NUMBER")

        print(f"🔑 VAPI_API_KEY present: {bool(api_key)}")
        print(f"🤖 assistant_id={assistant_id}")
        print(f"📱 phone_number_id={phone_number_id}")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "assistantId": assistant_id,
            "phoneNumberId": phone_number_id,
            "customer": {"number": phone_number},
            "assistantOverrides": {
                "variableValues": {
                    "name": caller_name,
                    "demoType": demo_type
                }
            }
        }

        print(f"📤 Sending Vapi payload:\n{json.dumps(payload, indent=2)}")
        response = requests.post("https://api.vapi.ai/call/phone", json=payload, headers=headers)

        print(f"📥 Vapi response status: {response.status_code}")
        print(f"📥 Vapi response body: {response.text}")

        return jsonify(response.json()), response.status_code

    except Exception as e:
        print(f"❌ initiate_call error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/vapi/calls', methods=['GET'])
def get_vapi_calls():
    try:
        print("📞 /api/vapi/calls called")
        limit = request.args.get("limit", 50)
        print(f"   limit={limit}")

        api_key = os.getenv("VAPI_API_KEY")
        if not api_key:
            print("❌ Missing VAPI_API_KEY")
            return jsonify({"error": "Missing VAPI_API_KEY"}), 500

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        url = f"https://api.vapi.ai/call?limit={limit}"

        assistant_id = os.getenv("VAPI_ASSISTANT_ID")
        if assistant_id:
            url += f"&assistantId={assistant_id}"

        print(f"📤 Fetching Vapi calls from URL: {url}")
        response = requests.get(url, headers=headers)

        print(f"📥 Vapi calls response status: {response.status_code}")
        print(f"📥 Vapi calls response length: {len(response.text)} chars")

        return jsonify(response.json()), response.status_code

    except Exception as e:
        print(f"❌ get_vapi_calls error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/appointments', methods=['GET'])
def get_appointments():
    try:
        print("📅 /api/appointments called")
        limit = int(request.args.get("limit", 10))
        print(f"   limit={limit}")

        events = list_appointments_logic(limit)
        print(f"✅ Returning {len(events)} appointment(s)")

        return jsonify([{
            "id": e["id"],
            "summary": e.get("summary", "Busy"),
            "start": e["start"].get("dateTime", e["start"].get("date")),
            "end": e["end"].get("dateTime", e["end"].get("date")),
            "status": e.get("status", "confirmed")
        } for e in events])

    except Exception as e:
        print(f"❌ get_appointments error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/vapi/tool/schedule-appointment', methods=['POST'])
def vapi_schedule_appointment():
    try:
        data = request.json or {}
        print("📩 Webhook schedule sequence initiated...")
        print(f"📥 Raw webhook payload:\n{json.dumps(data, indent=2, default=str)}")

        vars_payload = (
            data.get("variableValues")
            or data.get("message", {}).get("artifact", {}).get("variableValues")
            or data.get("assistant", {}).get("variableValues")
            or data.get("call", {}).get("assistantOverrides", {}).get("variableValues", {})
            or {}
        )

        print(f"🧠 Extracted variableValues:\n{json.dumps(vars_payload, indent=2, default=str)}")

        demo_type = vars_payload.get("demoType")
        if not demo_type:
            print("⚠️ Warning: demoType not detected. Defaulting to 'plumbing'.")
            demo_type = "plumbing"

        print(f"✅ Step 1: Demo type identified as '{demo_type}'")

        message = data.get("message", {})
        print(f"📨 Message object:\n{json.dumps(message, indent=2, default=str)}")

        tool_calls = message.get("toolCalls", [])
        if not tool_calls:
            print("ℹ️ Step 2: No tool calls found in the message. Exiting.")
            return jsonify({"status": "ignored", "message": "No function was triggered"}), 200

        print(f"✅ Step 2: Found {len(tool_calls)} function(s) triggered.")
        print(f"🚀 Step 3: Attempting to process tools for '{demo_type}' demo...")

        results = []

        for idx, tc in enumerate(tool_calls, start=1):
            try:
                print(f"🔧 Processing tool call #{idx}")
                print(f"   toolCallId={tc.get('id')}")

                function_name = tc.get("function", {}).get("name")
                print(f"   function_name={function_name}")

                raw_args = tc.get("function", {}).get("arguments", {})
                print(f"   raw_args type={type(raw_args)}")
                print(f"   raw_args value={raw_args}")

                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                print(f"   parsed_args={json.dumps(args, indent=2, default=str) if isinstance(args, dict) else args}")

                result_content = route_tool_by_demo_type(
                    demo_type=demo_type,
                    function_name=function_name,
                    args=args,
                    data=data
                )

                print(f"✅ Tool call #{idx} result: {result_content}")

                results.append({
                    "toolCallId": tc["id"],
                    "result": result_content
                })

            except Exception as inner_e:
                print(f"❌ Error processing individual tool call #{idx}: {inner_e}")
                results.append({
                    "toolCallId": tc.get("id"),
                    "result": f"Error: {str(inner_e)}"
                })

        print(f"📤 Returning webhook results:\n{json.dumps(results, indent=2, default=str)}")
        return jsonify({"results": results}), 200

    except Exception as e:
        print(f"❌ Webhook Critical Error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/health', methods=['GET'])
def health():
    print("💚 /health called")
    return jsonify({"status": "ok", "message": "API server is running"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3002))
    print(f"📊 API server running on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)