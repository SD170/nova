
<div align="center">

# 🎙️ STUDENT JARVIS  

## Your Student Life. One Intelligent Assistant.

**A Voice-First, Agentic AI Assistant for College Students**

**Canvas • Gmail • Google Calendar • Healthcare • Careers • News • AI Voice**

Built for **SunHacks 2026** | Arizona State University, Tempe


</div>

---

## ✨ The Idea  

College life happens across too many platforms: assignments in Canvas, updates in email, events in Google Calendar, internship opportunities online, and important news everywhere else.

Students shouldn't have to search through five different apps just to figure out what needs their attention.

**Student Jarvis brings everything together into one intelligent, voice-enabled assistant.**

Instead of simply answering questions, Jarvis is designed to understand what a student needs, gather relevant information, recommend actions, and complete approved tasks.

> **"Jarvis, what do I need to do today? Check Canvas and my emails, tell me what's urgent, and help me make time to study."**

Our vision is simple:

**One conversation. One assistant. Your entire student life.**

---

## 🌟 Core Features

### 🎙️ 1. Voice-First AI Assistant

Talk naturally to Jarvis and receive spoken responses.

- Real-time voice conversations
- Natural language understanding
- Spoken responses and explanations
- Text-based interaction as an alternative
- Personalized assistance using student context
- AI-powered task coordination
- Repeat, simplify, or slow down spoken explanations

**Example:**

> **Student:** "Hey Jarvis, what's on my schedule today?"
>
> **Jarvis:** "Good morning! You have two assignments coming up, one important email, and a meeting this afternoon. Would you like me to help you prioritize?"

### 🎓 2. Canvas Integration & Academic Assistant

Jarvis connects to Canvas LMS, with appropriate authorization, to help students stay organized academically.

**Features:**

- Retrieve courses and assignments
- Track assignment deadlines
- Identify upcoming exams
- Explain academic concepts
- Generate study guides
- Create practice quizzes
- Summarize available course materials
- Plan study sessions
- Organize coursework by priority

**Example:**

> "Jarvis, check Canvas and tell me what's due this week. Help me study for my Monday exam."

Jarvis can retrieve the relevant academic information and help the student create a realistic study plan.

### ✉️ 3. Gmail Integration & Smart Email Management

Jarvis helps students manage their inbox without manually opening every message.

**Features:**

- Summarize unread emails
- Identify important messages
- Prioritize emails requiring action
- Extract deadlines and meeting requests
- Detect relevant academic and career communications
- Draft email responses
- Read important emails aloud
- Create suggested follow-up tasks

**Example:**

> "Jarvis, summarize my unread emails and tell me which ones I need to respond to."

Jarvis identifies important information and provides a short, understandable summary.

Email drafts are reviewed and approved by the student before sending.

### 📅 4. Google Calendar & Smart Scheduling

Jarvis helps students manage their schedules across academic, career, and personal commitments.

**Features:**

- Read upcoming calendar events
- Identify available time slots
- Detect scheduling conflicts
- Suggest study sessions
- Organize appointments
- Create calendar events with confirmation
- Schedule reminders
- Suggest adjustments when priorities change

**Example:**

> "Jarvis, find an hour tomorrow to study for my exam and put it on my calendar."

Jarvis checks existing commitments, recommends an appropriate time, and creates the event after student approval.

### 📰 5. Personalized Current Events & News Notifications

Jarvis provides relevant news based on each student's interests.

**Features:**

- Personalized news feeds
- Technology and AI updates
- Political and world news
- Sports updates for selected teams
- Career and industry developments
- News related to academic subjects
- Customizable interest categories
- Optional breaking-news notifications
- Daily news summaries
- Spoken news briefings

**Example:**

> "Jarvis, give me a two-minute summary of today's AI news and updates about my favorite sports team."

Jarvis retrieves relevant news, identifies useful sources, and provides a concise summary.

Students control their notification preferences.

### 💼 6. AI Career & Internship Assistant

Jarvis supports students throughout their internship and career preparation.

**Features:**

- Research internship opportunities
- Discover relevant job openings
- Organize application deadlines
- Track opportunities
- Prepare interview questions
- Generate customized practice sessions
- Help improve resumes and cover letters
- Summarize job descriptions
- Suggest career-development activities

**Example:**

> "Jarvis, find AI and product management internships that match my background and help me prepare for upcoming interviews."

Jarvis can assist with research and preparation while keeping students in control of applications.

### 💚 7. Jarvis Care — Healthcare & Wellness Assistant

Jarvis Care makes everyday health information and appointment preparation more accessible to students.

**Features:**

- Voice-based wellness assistance
- Health appointment preparation
- Plain-language explanations of healthcare documents
- Medical bill and insurance terminology explanations
- Personalized appointment checklists
- Student wellness planning
- Follow-up task reminders
- Accessible health information
- Spoken explanations of user-provided instructions
- Integration with academic schedules for appointment planning

**Example:**

> "Jarvis, explain my doctor's instructions in simple words, read them aloud, and remind me about my follow-up appointment."

Jarvis provides understandable information and helps organize next steps.

**Jarvis Care does not diagnose conditions, prescribe medication, or replace qualified healthcare professionals.**
---

## ♿ Accessibility for Everyone

Accessibility is a core design principle of Student Jarvis.

We believe students should be able to use an intelligent assistant regardless of their visual, auditory, motor, or other accessibility needs.

### Voice Accessibility

- Two-way voice conversations
- Spoken responses to questions
- Adjustable speaking speed
- Repeat and rephrase commands
- Simple, understandable language
- Hands-free interaction

### Visual Accessibility

- Large-text mode
- Zoom-friendly interface
- High-contrast display options
- Screen-reader compatibility
- Clear typography and visual hierarchy
- Responsive layouts

### Motor Accessibility

- Keyboard navigation
- Accessible buttons and controls
- Large interaction targets
- Minimal reliance on complicated gestures
- Alternative text-based interactions

### Hearing Accessibility

- Live conversation transcripts
- Written alternatives to spoken responses
- Visual notifications
- Captions for supported audio content

### Inclusive User Experience

- Reduced-motion support
- Clear navigation
- Consistent layouts
- Accessible notifications
- User-controlled accessibility settings

**Design target: WCAG 2.2 AA accessibility standards.**

---

## 🧠 What Makes Student Jarvis Different?

Most student productivity applications focus on one task.

Student Jarvis is designed to connect multiple student needs through a shared AI system.

Rather than having separate assistants for academics, email, scheduling, and wellness, Jarvis coordinates information across different services.

### Example: One Request, Multiple Agents

**Student:**

> "Jarvis, I have an exam Monday, an internship interview Tuesday, and a doctor's appointment I need to schedule. Help me organize everything."

**Jarvis coordinates:**

1. **Academic Agent:** Retrieves exam information and generates a study plan.
2. **Career Agent:** Prepares interview practice tasks.
3. **Healthcare Agent:** Helps prepare for the appointment.
4. **Calendar Agent:** Checks available time slots and scheduling conflicts.
5. **Voice Assistant:** Explains the plan aloud and asks for confirmation before making changes.

**Result:** One coordinated plan instead of several disconnected applications.

---

## 🏗️ System Architecture

```text
                    STUDENT
                  Voice / Text
                       |
                       v
             STUDENT JARVIS UI
                       |
                       v
              VAPI VOICE LAYER
                       |
                       v
               AI ORCHESTRATOR
                       |
       +---------------+---------------+
       |               |               |
       v               v               v
   ACADEMIC         PRODUCTIVITY     PERSONAL
    AGENTS             AGENTS         AGENTS
       |               |               |
     Canvas           Gmail          Healthcare
     Quizzes          Calendar       News
     Study Plans      Tasks          Careers
       |               |               |
       +---------------+---------------+
                       |
                       v
             AI REASONING & MEMORY
                       |
                       v
               ACTION PLANNING
                       |
                       v
              USER CONFIRMATION
                       |
                       v
              EXECUTE & VERIFY
                       |
                       v
              VOICE + UI RESPONSE
```

### Technology Stack

| Component | Technology |
|---|---|
| Voice Assistant | Vapi |
| Backend | Python, FastAPI |
| AI Reasoning | Gemini |
| Academic Integration | Canvas LMS API |
| Email | Gmail API |
| Scheduling | Google Calendar API |
| News | Google News RSS, ESPN, Hacker News |
| Memory | supermemory |
| Vector Search | MongoDB Atlas |
| Web Research | TinyFish |
| Agent Infrastructure | Maritime |
| Cloud Infrastructure | AWS |
| Development | GitHub, Cursor, Claude Code |

*Technologies listed include current prototypes, planned integrations, and hackathon sponsor targets. Not all integrations are verified as complete.*

---

## 📂 Repository Structure

```text
student-jarvis/
│
├── AGENTS.md
├── README.md
├── shared.env
│
├── context/
│   └── Project documentation
│
├── apps/
│   ├── voice/
│   ├── ui/
│   ├── orchestrator/
│   ├── browser-agent/
│   └── retrieval-quiz/
│
├── drafts/
│   └── amrita-current-events/
│
├── packages/
│   ├── schemas/
│   └── mocks/
│
└── infra/
```

The repository is actively evolving as individual components are developed and integrated.

---

## 🚀 Getting Started

### 1. Clone the Repository

```bash
git clone git@github.com:SD170/student-jarvis.git
cd student-jarvis
```

The repository is private, so GitHub access is required.

### 2. Review Project Instructions

Read the repository's `AGENTS.md` and the files in `context/` before making changes.

### 3. Configure Environment Variables

Each integration may require its own credentials, including:

- Vapi API credentials
- Google OAuth credentials
- Canvas authorization
- Gemini API credentials
- Optional news service credentials
- Database and deployment configuration

Store secrets in local environment files or a secure secrets manager.

**Never commit API keys, passwords, or OAuth tokens to GitHub.**

### 4. Run Individual Components

Follow the startup instructions for each service as the team completes integration.

Mock data may be used during development to demonstrate features without accessing real student accounts.

### 5. Connect Student Services

Students explicitly authorize the services Jarvis needs to access.

Supported services and authentication workflows will be expanded as development progresses.

---

## 🔒 Privacy, Security & Responsible AI

Student Jarvis is designed to put users in control of their information and actions.

Key principles include:

- Secure OAuth-based integrations
- Minimal permissions
- Secure storage of authentication tokens
- User-controlled data access
- Optional notifications
- Ability to disconnect supported integrations
- Clear distinction between live and simulated data
- Protection against malicious instructions embedded in retrieved documents
- Confirmation before externally visible actions
- Clear communication of AI limitations
- Responsible handling of academic and health information

Jarvis should never claim that an action succeeded unless the connected service confirms completion.

---

## 🛠️ Development Status

Student Jarvis is under active development for SunHacks 2026.

The following reflects the repository information available as of November 14, 2026.

| Feature | Status |
|---|---|
| Vapi Voice Assistant | Initial prototype implemented |
| Voice Web UI | Initial prototype implemented |
| FastAPI Voice Webhook | Initial implementation |
| Current Events & News | Draft prototype with offline tests |
| Canvas Integration | Planned / implementation to verify |
| Academic Quiz Generation | Planned / implementation to verify |
| Gmail Integration | Planned |
| Google Calendar Integration | Planned |
| Career Assistant | Planned / implementation to verify |
| Jarvis Care | Planned / implementation to verify |
| Cross-Agent Orchestration | Scaffolded / end-to-end testing required |
| Accessibility Features | Design requirements established |

Some features may initially use mock data or demonstration workflows.

The team will update implementation status as integrations are completed and tested.

---

## 🎬 SunHacks 2026 Demo

### Scenario: A Student's AI-Powered Day

A student starts their morning with one question:

> **"Hey Jarvis, what do I need to know today?"**

Jarvis provides a personalized briefing:

**Academics**

"Your computer science assignment is due tomorrow, and you have an exam coming up Monday."

**Email**

"You have three important emails. One needs a response from you."

**Calendar**

"You have a meeting at 2 PM. I found an open study window from 4 to 5 PM."

**Current Events**

"There's a major AI industry announcement related to your interests. Would you like a short summary?"

**Next Action**

"Would you like me to schedule your study session and help you prepare for your exam?"

The student responds:

> "Yes, schedule the study session and quiz me on the exam material."

Jarvis coordinates the requested actions, obtains confirmation where needed, and responds with a clear spoken summary.

The demo should distinguish live integrations from simulated data and only claim actions that actually execute successfully.

---

## 🎯 Our Mission

We believe the next generation of student technology should be more than a collection of disconnected applications.

It should be accessible, intelligent, personalized, and genuinely useful.

Student Jarvis aims to reduce the time students spend managing tools so they can focus on learning, growth, and their everyday lives.

**Less switching tabs. More getting things done.**

---

## 👥 Meet the Team

Built by a team of four at **SunHacks 2026**, Arizona State University.

- [Saswata Dutta](https://github.com/SD170)
- [Abishek Prakash](https://github.com/Abishek1801)
- [Amrita Seeram](https://github.com/AmritaSeeram)
- [Shruti Pochiraju Sai](https://github.com/shrutipochiraju-sai)

---

<div align="center">

# 🎙️ STUDENT JARVIS

### Your Student Life. One Intelligent Assistant.

**Built with AI. Designed for Students. Accessible to Everyone.**

**SunHacks 2026 | Arizona State University**

</div>
