🎙️ Student Jarvis
Your student life. One intelligent assistant.
A voice-first, agentic AI assistant that helps students stay on top of classes, communication, schedules, current events, and everyday well-being.

Built for SunHacks 2026 · Arizona State University, Tempe
</div>✨ The idea
College life happens across too many platforms: assignments in Canvas, updates in email, events in Google Calendar, internship opportunities online, and important news everywhere else. Students shouldn't have to search through five tabs just to figure out what needs their attention.

Student Jarvis brings those pieces together. Instead of only answering questions, Jarvis is designed to understand what a student needs, gather relevant information from authorized services, recommend the next action, and carry it out with the student's approval.
“Jarvis, what do I need to do today? Check Canvas and my emails, tell me what's urgent, and help me make time to study.”

The goal is one simple, natural conversation that turns scattered information into a clear plan.
🌟 Core experiences
Capability	What Jarvis should do
🎓 Canvas & academics	Retrieve courses, assignments, deadlines, and available class materials; explain topics; generate study guides and quizzes; help break down coursework without doing graded work dishonestly.
✉️ Email intelligence	Read authorized inbox messages, provide short spoken or written digests, identify messages needing a response, extract deadlines, and draft replies for review.
📅 Smart calendar	Find free time, propose study sessions and appointments, identify conflicts, and create or update calendar events after confirmation.
📰 Personalized news	Surface relevant current events based on chosen interests such as technology, politics, sports teams, career fields, and course topics; deliver optional notifications and spoken summaries.
💼 Career assistance	Research relevant internships and jobs, organize opportunities, and help prepare application materials and interviews.
💚 Jarvis Care	Offer accessible wellness check-ins, appointment preparation, and plain-language explanations of healthcare information without replacing a clinician.
🎤 Voice-first control	Let students ask naturally, hear Jarvis speak its response, request a repeat or simpler explanation, and complete equivalent tasks by text.


🧠 What makes Jarvis different?
Jarvis is meant to coordinate across tools, not act as a collection of unrelated chatbots. For example, it could recognize an exam deadline from Canvas, find related messages in Gmail, suggest study blocks in Calendar, and then read a short plan aloud—all from one request.
🗣️ Example conversations
Start-of-day briefing
Student: “Hey Jarvis, catch me up.”
Jarvis: “You have two assignments coming up, one email that needs a reply, and a meeting this afternoon. Would you like me to walk you through the urgent items first?”

Assignment planning
Student: “What's due in Canvas this week? Quiz me on the material for Monday's exam and fit in two review sessions.”

Email triage
Student: “Summarize my unread emails, tell me which ones need action, and draft a response to my professor.”

Calendar scheduling
Student: “Find an hour after class tomorrow for interview preparation and put it on my calendar.”

News alerts
Student: “Give me a two-minute update on AI news and my favorite sports team. Only notify me when something important happens.”

Accessible care support
Student: “Jarvis, read my appointment checklist out loud, slowly, and help me find a time that doesn't conflict with class.”

♿ Accessibility by design
Student Jarvis is designed to be voice-first, never voice-only. Accessibility should work across the entire application, not just one module.
- Two-way speech: Speech input with audible responses, plus visible transcripts and text input.
- Understandable language: Short explanations, repeat/rephrase controls, adjustable speaking rate, and simple summaries.
- Low-vision support: Readable typography, strong contrast, adjustable text sizes, and responsive layouts at high browser zoom.
- Motor-access support: Full keyboard navigation, visible focus indicators, generous touch targets, and no voice-only mandatory actions.
- Screen-reader support: Semantic elements, labeled controls, status announcements, and sensible focus management.
- Sensory preferences: Reduced-motion support, non-audio alternatives to notifications, and controls for alert frequency.
Accessibility target: WCAG 2.2 AA, with manual and automated checks. Actual conformance must be tested rather than assumed.
🔐 Privacy, safety & user control
Jarvis should request only the permissions needed for each connected feature and explain what that access allows.
- Connect accounts using OAuth; keep access tokens and secrets on the backend, not in the frontend or repository.
- Allow students to disconnect integrations and delete stored data where supported.
- Treat retrieved emails, assignments, and documents as untrusted content; never follow instructions embedded inside them as if they were commands to the assistant.
- Require explicit confirmation before sending email, adding or changing calendar events, submitting applications, or taking other externally visible actions.
- Make notifications opt-in, configurable, and easy to pause.
- Never claim to have read an inbox, opened Canvas, booked an appointment, or created an event unless the underlying integration confirms success.
- Health responses should be educational and supportive, not diagnoses or prescriptions.
- Any meeting assistant must be visibly identified, respect host admission and consent, and avoid recording without appropriate permission.
🧩 System design
                STUDENT (VOICE OR TEXT)
                          |
                Accessible Jarvis UI
                          |
                 Voice / Vapi layer
                          |
                  Agent Orchestrator
                          |
        +-----------------+------------------+
        |                 |                  |
   Academic Agent    Productivity Agent   Personal Agent
        |                 |                  |
      Canvas         Gmail / Calendar    News / Career / Care
        |                 |                  |
        +-----------------+------------------+
                          |
              Context / Memory / Reasoning
                          |
            Proposed actions + confirmation
                          |
              Spoken + visual response
Each integration should expose a small, predictable interface to the orchestrator. The shared UI and voice layer should not need to know the implementation details of Canvas, Gmail, Calendar, or news retrieval.
Technology direction
Layer	Technology / integration
Voice	Vapi browser voice assistant and webhook integration
Backend	Python / FastAPI services
AI reasoning	Gemini and agent tool orchestration
Academic data	Canvas LMS API with institution-authorized access
Email & scheduling	Gmail API and Google Calendar API via Google OAuth
Current events	Google News RSS, ESPN, Hacker News; optional NewsAPI
Context and retrieval	supermemory and MongoDB Atlas (integration targets)
Additional research	TinyFish (integration target)
Hosting / compute	Maritime and/or AWS (integration targets)


The table reflects the intended architecture and sponsor-aligned technologies; not every integration is necessarily implemented or enabled.
📂 Repository structure
student-jarvis/
├── AGENTS.md                   # Team / AI coding-agent instructions
├── README.md
├── shared.env                 # Shared non-secret configuration
├── context/                   # Project context and team documentation
├── apps/
│   ├── voice/                 # Vapi voice client and FastAPI webhook
│   ├── ui/                    # Main student interface
│   ├── orchestrator/          # Tool routing / shared reasoning
│   ├── browser-agent/         # Browser-based workflows
│   └── retrieval-quiz/        # Academic retrieval / quiz flows
├── drafts/
│   └── amrita-current-events/ # News alerts and digest prototype
├── packages/
│   ├── schemas/               # Shared data contracts
│   └── mocks/                 # Development/demo data
└── infra/                     # Infrastructure configuration
The repository is actively evolving; component ownership and paths may change as teammates integrate their work.
🚀 Getting started
1. Clone the repository (requires access; the repository is private):
git clone git@github.com:SD170/student-jarvis.git
cd student-jarvis
2. Read the shared development instructions:
AGENTS.md
context/
3. Configure only the components you are developing. The voice service has an apps/voice/.env.example template. Use local environment variables for Vapi, Google OAuth, Canvas, and other provider credentials as each integration is enabled. Never commit real keys or tokens.

4. Run the selected component according to its own service instructions. During development, mocked connectors may be used to demonstrate the experience without requesting access to real student accounts.

5. Connect integrations individually. Students explicitly authorize Canvas, Gmail, Google Calendar, and other services before Jarvis accesses personal information.
Note: There is not yet a single verified one-command startup path for all services in this README. The team should add it after end-to-end integration and testing.

🛠️ Development status
The following reflects the shared repository snapshot from November 14, 2026. It distinguishes code that has been described in commits from product-level integrations that still require verification.
Area	Status at this snapshot
Voice assistant	Initial implementation present: Vapi-based browser UI, FastAPI webhook, assistant setup utilities, and a set_name tool
Personalized news	Draft/prototype present: News digest endpoints, notification UI, spoken digest, and offline tests
Canvas academic tools	Planned / integration to verify
Gmail summaries and action triage	Planned
Calendar event creation	Planned
Career assistance	Planned / integration to verify
Healthcare module	Planned / integration to verify
Cross-agent orchestration	Architecture scaffolded; end-to-end behavior to verify


A working UI or mocked response is not the same as a verified external integration. Update this table as the team tests each workflow.
🎬 SunHacks demo
Demo scenario: A student asks Jarvis to prepare them for the week.
1. Student asks by voice: “Jarvis, what needs my attention?”
2. Jarvis gathers authorized Canvas deadlines, actionable emails, and upcoming calendar events.
3. Jarvis gives a concise spoken summary and visual priority list.
4. Student asks for a study plan; Jarvis suggests open times around existing commitments.
5. After the student confirms, Jarvis creates the selected calendar event and verifies the result.
6. Student asks for a short news briefing, and Jarvis responds aloud with sources.
For an honest demo, identify which data is live, which is simulated, and which actions are actually executed.
👥 Team
Created at SunHacks 2026, Arizona State University by the Student Jarvis team:
- Saswata Dutta
- Abishek Prakash
- Amrita Seeram
- Shruti Pochiraju Sai
<div align="center">Less switching tabs. More getting things done.
Student Jarvis — a smarter way to navigate student life.
</div>
