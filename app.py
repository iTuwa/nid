from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import os
import requests


VAPI_API_KEY = os.getenv("VAPI_API_KEY")
VAPI_ASSISTANT_ID = os.getenv(
    "VAPI_ASSISTANT_ID", "99f163af-0fba-432a-9f2c-3ea9b6f49f25"
)


# Dummy PIN-protected results data.
# In a real deployment you would replace this with a database or secure API.
RESULTS_BY_PIN = {
    "1234": {
        "student_name": "Aisha Ibrahim",
        "class": "Year 6 Zebra",
        "session": "2024/2025",
        "term": "Second Term",
        "subjects": {
            "mathematics": {"score": 88, "grade": "A"},
            "english": {"score": 82, "grade": "A-"},
            "science": {"score": 79, "grade": "B+"},
            "social studies": {"score": 85, "grade": "A"},
        },
    },
    "5678": {
        "student_name": "David Okafor",
        "class": "Year 9 Beryl",
        "session": "2024/2025",
        "term": "Second Term",
        "subjects": {
            "mathematics": {"score": 72, "grade": "B"},
            "english": {"score": 90, "grade": "A+"},
            "physics": {"score": 76, "grade": "B+"},
            "chemistry": {"score": 69, "grade": "C+"},
        },
    },
}


def create_app() -> Flask:
    app = Flask(__name__)
    CORS(app)

    @app.get("/health")
    def health_check():
        """Simple health check endpoint for Render and local tests."""
        return jsonify({"status": "ok", "service": "nimschools-assistant"})

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.post("/assistant")
    def assistant():
        """Main endpoint Vapi (or any client) can call with a user's question.

        Expected JSON body (you can map this from Vapi's tool arguments):
        {
          "question": "..."  # primary field the assistant will use
        }
        """
        data = request.get_json(silent=True) or {}
        question = (data.get("question") or data.get("query") or "").strip()

        if not question:
            return (
                jsonify(
                    {
                        "answer": None,
                        "error": "Missing 'question' in request body.",
                    }
                ),
                400,
            )

        answer = answer_question(question)
        return jsonify({"answer": answer})

    @app.post("/results")
    def results_lookup():
        """Return a student's result for a given subject, protected by a PIN.

        Expected JSON body:
        {
          "pin": "1234",          # required
          "subject": "math"       # optional; if missing, return all subjects
        }
        """

        data = request.get_json(silent=True) or {}
        pin = (data.get("pin") or "").strip()
        subject_raw = (data.get("subject") or "").strip().lower()

        if not pin:
            return jsonify({"error": "Missing 'pin' in request body."}), 400

        record = RESULTS_BY_PIN.get(pin)
        if not record:
            # Do not reveal whether the PIN is close/valid; just say it's invalid.
            return jsonify({"error": "Invalid PIN. Please check and try again."}), 403

        subjects = record["subjects"]

        if not subject_raw:
            # Return all subjects for this PIN
            return jsonify({
                "student_name": record["student_name"],
                "class": record["class"],
                "session": record["session"],
                "term": record["term"],
                "subjects": subjects,
            })

        # Normalise some common subject aliases
        alias_map = {
            "math": "mathematics",
            "maths": "mathematics",
            "english language": "english",
        }
        subject_key = alias_map.get(subject_raw, subject_raw)

        subject_result = subjects.get(subject_key)
        if not subject_result:
            return jsonify({
                "error": f"No recorded result for subject '{subject_raw}' for this student.",
            }), 404

        return jsonify({
            "student_name": record["student_name"],
            "class": record["class"],
            "session": record["session"],
            "term": record["term"],
            "subject": subject_key,
            "score": subject_result["score"],
            "grade": subject_result["grade"],
        })

    @app.post("/vapi/make-call")
    def vapi_make_call():
        if not VAPI_API_KEY:
            return jsonify({"error": "VAPI_API_KEY is not configured"}), 500

        data = request.get_json(silent=True) or {}
        assistant_id = data.get("assistant_id") or VAPI_ASSISTANT_ID
        customer_number = (data.get("customer_number") or "").strip()
        phone_number_id = data.get("phone_number_id")

        if not customer_number:
            return (
                jsonify({"error": "customer_number is required"}),
                400,
            )

        payload = {
            "assistantId": assistant_id,
            "customer": {"number": customer_number},
        }

        if phone_number_id:
            payload["phoneNumberId"] = phone_number_id

        headers = {
            "Authorization": f"Bearer {VAPI_API_KEY}",
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(
                "https://api.vapi.ai/call",
                json=payload,
                headers=headers,
                timeout=30,
            )
        except requests.RequestException as exc:
            return (
                jsonify({"error": f"Error contacting Vapi: {exc}"}),
                502,
            )

        if response.status_code >= 400:
            return (
                jsonify({"error": response.text}),
                response.status_code,
            )

        try:
            body = response.json()
        except ValueError:
            body = {"raw": response.text}

        return jsonify(body)

    @app.get("/vapi/assistant-config")
    def vapi_assistant_config():
        """Return assistant configuration for the Vapi web widget.

        Mirrors the structure from voa-main/main.py but with a NimSchools-specific
        system prompt so Vapi can run a voice assistant for New Ideal Model Schools.
        """

        system_prompt = (
            "System Role:\n"
            "You are the official virtual assistant for New Ideal Model Schools (NIMS)\n"
            "in Jalingo, Taraba State, Nigeria. You speak clearly, warmly, and concisely.\n\n"
            "Audience:\n"
            "- You are primarily speaking to parents and guardians who are considering\n"
            "  enrolling their children, as well as prospective students and visitors.\n\n"
            "Your primary job is to answer questions about NIMS based on the details\n"
            "provided here. When you don't know something, you must say you are not sure\n"
            "and direct the user to contact the school by phone or email instead of\n"
            "making things up.\n\n"
            "Key facts you can rely on:\n"
            "- Name: New Ideal Model Schools (NIMS).\n"
            "- Location: No. 12 Old Pantisawa Road, Jalingo, Taraba State, Nigeria.\n"
            "- Contact phone: +234 803 426 1645.\n"
            "- Contact email: info@nimschools.org.\n"
            "- Motto / focus: Developing lifelong learning through quality education in\n"
            "  a vibrant learning environment.\n\n"
            "Academics:\n"
            "- NIMS offers Early Years Foundation Stage (EYFS) through Key Stages 1–4.\n"
            "- EYFS includes classes like Playgroup Lily, Pre-Nursery Jasmine, Pre-Nursery Tulip, Nursery Daisy, Nursery Ivy, and Reception classes such as Sage and Rose.\n"
            "- Key Stage 1 includes classes such as Year 1 Cheetah, Year 2 Dolphin, Year 2 Orca, and Year 3 Bear.\n"
            "- Key Stage 2 includes Year 4 Blue Jays, Year 5 Barn Owls, and Year 6 Zebra.\n"
            "- Key Stage 3 includes Year 7 Amber, Year 8 Ruby, and Year 9 Beryl.\n"
            "- Key Stage 4 includes Year 10 Jasper, Year 11 Onyx, and Year 12 Topaz.\n"
            "- The school encourages holistic development through extracurricular activities such as an art gallery and architectural design projects.\n\n"
            "Leadership and staff (mention only when relevant to the question):\n"
            "- Principal / Head of Schools: Mr. Adebanjo Oluwafemi.\n"
            "- Vice Principal Academic: Mrs. Ifeoma Victoria Onwuka.\n"
            "- Vice Principal Special Duties: Mr. David Kennedy.\n"
            "- Art Teacher: Mr. Baajon Cyracus Michael.\n"
            "- ICT Staff and E-Librarian: Samuel Oguche.\n\n"
            "Alumni sentiment:\n"
            "- Alumni describe NIMS as the best school and say it has positively impacted them and their generation, helping them become more brilliant and competitive.\n\n"
            "Safety and limitations:\n"
            "- If a user asks about fees, transport, boarding, or other detailed logistics that are not explicitly listed, clearly say that exact details can change and they should contact the school directly at the phone number or email above.\n"
            "- Do not invent data about exam results, fees, or policies.\n\n"
            "Tone and style:\n"
            "- Sound like a modern, friendly school advisor, not a chatbot.\n"
            "- Be warm, reassuring, and parent- and student-friendly while staying professional.\n"
            "- Keep answers short and to the point unless the user asks for more detail.\n"
            "- When helpful, briefly highlight NIMS strengths such as caring teachers, a safe environment, strong academics, and rich extracurricular activities.\n"
            "- Use natural, conversational language and avoid repeating the exact same phrases too often.\n"
        )

        config = {
            "model": {
                "provider": "openai",
                "model": "gpt-4.1-mini",
                "messages": [
                    {
                        "role": "system",
                        "content": system_prompt,
                    }
                ],
            },
        }

        return jsonify(config)

    return app


def answer_question(question: str) -> str:
    """Very simple rule-based QA for NimSchools based on the public website.

    This is intentionally transparent and deterministic so you can see what the
    assistant will say. You can later replace this with a real LLM call if you
    want, keeping the same Flask contract.
    """
    q = question.lower()

    # Location / contact
    if any(word in q for word in ["address", "location", "where are you", "where is the school"]):
        return (
            "New Ideal Model Schools (NIMS) is located at No. 12 Old Pantisawa Road, "
            "Jalingo, Taraba State, Nigeria."
        )

    if any(word in q for word in ["contact", "phone", "call", "email"]):
        return (
            "You can contact New Ideal Model Schools at +234 803 426 1645 or "
            "by email at info@nimschools.org. The school is at No. 12 Old Pantisawa "
            "Road, Jalingo, Taraba State."
        )

    # General about the school
    if any(word in q for word in ["about", "tell me about", "what is nim", "what is nims", "new ideal model schools"]):
        return (
            "New Ideal Model Schools (NIMS) in Jalingo, Taraba State, focuses on "
            "developing lifelong learning through quality education. The school "
            "provides a vibrant learning environment with modern classrooms, "
            "state-of-the-art facilities, and engaged students, and encourages "
            "holistic development through academics and extracurricular activities."
        )

    # Admissions
    if "admission" in q or "enrol" in q or "enroll" in q or "apply" in q:
        return (
            "Admissions for the 2025 academic year are open. The website links to "
            "an admissions page where you can apply. If you need help with the "
            "process, you can also call +234 803 426 1645 or email info@nimschools.org "
            "for guidance on requirements, fees, and timelines."
        )

    # Academics: EYFS and Key Stages
    if "early years" in q or "eyfs" in q:
        return (
            "Early Years Foundation Stage (EYFS) at NIMS includes classes like "
            "Playgroup Lily, Pre-Nursery Jasmine, Pre-Nursery Tulip, Nursery Daisy, "
            "Nursery Ivy, and Reception classes such as Sage and Rose."
        )

    if "key stage 1" in q or "ks1" in q or "key stage one" in q:
        return (
            "Key Stage 1 at NIMS includes Year 1 Cheetah, Year 2 Dolphin, Year 2 Orca, "
            "and Year 3 Bear classes."
        )

    if "key stage 2" in q or "ks2" in q or "key stage two" in q:
        return (
            "Key Stage 2 at NIMS includes Year 4 Blue Jays, Year 5 Barn Owls, and "
            "Year 6 Zebra."
        )

    if "key stage 3" in q or "ks3" in q or "key stage three" in q:
        return (
            "Key Stage 3 at NIMS includes Year 7 Amber, Year 8 Ruby, and Year 9 Beryl."
        )

    if "key stage 4" in q or "ks4" in q or "key stage four" in q:
        return (
            "Key Stage 4 at NIMS includes Year 10 Jasper, Year 11 Onyx, and Year 12 Topaz."
        )

    if "class" in q or "classes" in q or "grades" in q or "sections" in q:
        return (
            "NIMS runs from Early Years Foundation Stage (EYFS) through Key Stages 1–4. "
            "EYFS covers playgroup and nursery up to reception; Key Stage 1 covers Years 1–3; "
            "Key Stage 2 covers Years 4–6; Key Stage 3 covers Years 7–9; and Key Stage 4 "
            "covers Years 10–12."
        )

    # Extracurricular activities
    if "extracurricular" in q or "extra-curricular" in q or "activities" in q or "club" in q or "sport" in q:
        return (
            "NIMS encourages holistic development through extracurricular activities, "
            "including an art gallery, architectural design projects, and other clubs "
            "and activities that support students' creativity and talents."
        )

    # Staff & leadership
    if "principal" in q or "head of school" in q or "head of schools" in q:
        return (
            "The Principal and Head of Schools at NIMS is Mr. Adebanjo Oluwafemi. "
            "He has extensive experience in education and school leadership across "
            "international schools in Nigeria."
        )

    if "vice principal academic" in q or "vp academic" in q or "ifeoma" in q:
        return (
            "The Vice Principal Academic at NIMS is Mrs. Ifeoma Victoria Onwuka. "
            "She supports curriculum development and teacher effectiveness to ensure "
            "strong academic outcomes."
        )

    if "vice principal" in q or "special duties" in q or "david kennedy" in q:
        return (
            "The Vice Principal Special Duties at NIMS is Mr. David Kennedy. He helps "
            "oversee daily operations and resources to maintain a safe and organized "
            "learning environment."
        )

    if "art teacher" in q or "baajon" in q or "cyracus" in q:
        return (
            "The Art Teacher at NIMS is Mr. Baajon Cyracus Michael. He develops and "
            "delivers engaging art lessons, helping students explore drawing, painting, "
            "sculpture, and art appreciation."
        )

    if "e-librarian" in q or "ict staff" in q or "samuel oguche" in q:
        return (
            "Samuel Oguche serves as ICT staff and E-Librarian at NIMS, supporting "
            "students' access to digital learning resources."
        )

    # Testimonials / alumni
    if "alumni" in q or "testimonials" in q or "what do students say" in q:
        return (
            "Alumni of NIMS describe it as the best school and say it has positively "
            "impacted them and their generation. They highlight how studying at NIMS "
            "helped them understand what education is really about and made them more "
            "brilliant and competitive."
        )

    # Fees, transport, boarding etc. (not clearly listed on the page we scraped)
    if any(word in q for word in ["fees", "school fees", "tuition", "scholarship", "bus", "transport", "boarding", "hostel"]):
        return (
            "Details like fees, transport, and boarding are not clearly listed in the "
            "public content I can see. Please contact the school directly at "
            "+234 803 426 1645 or info@nimschools.org for the latest information."
        )

    # Fallback
    return (
        "I'm a NimSchools helper bot with information taken from the public website. "
        "I couldn't find an exact answer to that question. You can:\n"
        "- Ask about academics (EYFS, Key Stages 1–4, extracurricular activities).\n"
        "- Ask about the principal, vice principals, or staff.\n"
        "- Ask for contact details or the school location.\n\n"
        "For anything else (like fees or detailed admission requirements), it's best to "
        "call +234 803 426 1645 or email info@nimschools.org."
    )


app = create_app()
