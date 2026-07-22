import re

# Fix API_HANDBOOK.md
with open('API_HANDBOOK.md', 'r') as f:
    content = f.read()

# Remove user auth token from endpoints
content = re.sub(r'Authorization: Bearer <user_access_token>\n', '', content)
content = re.sub(r'-H "Authorization: Bearer \$USER_TOKEN" \\\n\s*', '', content)
content = re.sub(r'-H "Authorization: Bearer \$USER_TOKEN"\n?', '', content)

# Update descriptions
content = content.replace('User | Restricted — checks availability, books/reschedules/cancels their own appointments, uses chatbot | `POST /api/accounts/register/`', 'User | Anonymous — uses email to check availability, book, reschedule, and cancel via chatbot | (No registration needed)')

# Update endpoint auth table
content = content.replace('| `GET`  | `/api/calendar/availability/` | User |', '| `GET`  | `/api/calendar/availability/` | Public |')
content = content.replace('| `POST` | `/api/appointments/book/` | User |', '| `POST` | `/api/appointments/book/` | Public |')
content = content.replace('| `GET`  | `/api/appointments/mine/` | User |', '| `GET`  | `/api/appointments/by-email/` | Public |')
content = content.replace('| `PATCH`| `/api/appointments/<id>/reschedule/` | User |', '| `PATCH`| `/api/appointments/<id>/reschedule/` | Public |')
content = content.replace('| `DELETE`| `/api/appointments/<id>/cancel/` | User |', '| `DELETE`| `/api/appointments/<id>/cancel/` | Public |')
content = content.replace('| `POST` | `/api/chat/sessions/` | User |', '| `POST` | `/api/chat/sessions/` | Public |')
content = content.replace('| `POST` | `/api/chat/message/` | User |', '| `POST` | `/api/chat/message/` | Public |')
content = content.replace('| `GET`  | `/api/chat/sessions/<id>/messages/` | User |', '| `GET`  | `/api/chat/sessions/<id>/messages/` | Public |')
content = content.replace('| `DELETE`| `/api/chat/sessions/<id>/` | User |', '| `DELETE`| `/api/chat/sessions/<id>/` | Public |')

# Other replacements
content = content.replace('mine/', 'by-email/?email=<user_email>')
content = content.replace('session_id', 'session_key')

with open('API_HANDBOOK.md', 'w') as f:
    f.write(content)

# Fix context/overview.md
with open('context/overview.md', 'r') as f:
    content = f.read()

content = content.replace(
    '| **User** | Registered Django `User` | Self-registers, logs in with JWT, interacts with chatbot to book/manage appointments |',
    '| **User** | Anonymous (Email-based) | Accesses the chatbot and booking endpoints anonymously. Identified exclusively by their email. |'
)
content = content.replace(
    '1. User sends POST /api/chat/message/ with JWT\n2. Django authenticates user via JWT middleware',
    '1. User sends POST /api/chat/message/ with session_key\n2. Django loads session via session_key UUID'
)
content = content.replace(
    '| **Users are Django Users, not anonymous** | Bookings need to be attributable; users must log in to reschedule/cancel their own appointments. |',
    '| **Users are Anonymous** | Frictionless booking. Bookings are tied to the email address provided during chat. |'
)
content = content.replace(
    '| `/api/calendar/availability/` | GET | Find open time slots | `IsAuthenticated` |',
    '| `/api/calendar/availability/` | GET | Find open time slots | `AllowAny` |'
)
content = content.replace(
    '| `/api/appointments/book/` | POST | Book an appointment | `IsAuthenticated` |',
    '| `/api/appointments/book/` | POST | Book an appointment | `AllowAny` |'
)
content = content.replace(
    '| `/api/appointments/mine/` | GET | List own bookings | `IsAuthenticated` |',
    '| `/api/appointments/by-email/` | GET | List bookings for an email | `AllowAny` |'
)
content = content.replace(
    '| `/api/appointments/<id>/reschedule/` | PATCH | Modify a booking | `IsAuthenticated` |',
    '| `/api/appointments/<id>/reschedule/` | PATCH | Modify a booking | `AllowAny` |'
)
content = content.replace(
    '| `/api/appointments/<id>/cancel/` | DELETE | Cancel a booking | `IsAuthenticated` |',
    '| `/api/appointments/<id>/cancel/` | DELETE | Cancel a booking | `AllowAny` |'
)

with open('context/overview.md', 'w') as f:
    f.write(content)

print("Documentation updated successfully")
