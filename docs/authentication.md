# OneSuite Backend - JWT Authentication

This document describes the JWT authentication system for the OneSuite Advisory Platform backend.

## Authentication Endpoints

All authentication endpoints are under `/api/users/auth/`:

| Endpoint | Method | Auth Required | Description |
|----------|--------|---------------|-------------|
| `/api/users/auth/login/` | POST | No | Obtain access and refresh tokens |
| `/api/users/auth/refresh/` | POST | No | Get new access token using refresh token |
| `/api/users/auth/logout/` | POST | Yes | Blacklist refresh token |
| `/api/users/auth/me/` | GET | Yes | Get current user profile |

## Token Lifetimes

- **Access Token**: 15 minutes
- **Refresh Token**: 7 days

## Usage Examples

### 1. Login

**Request:**
```bash
curl -X POST https://onesuite-backend-86225501431.asia-southeast1.run.app/api/users/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"username": "your_username", "password": "your_password"}'
```

**Response:**
```json
{
  "refresh": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "access": "eyJ0eXAiOiJKV1QiLCJhbGc..."
}
```

### 2. Access Protected Resource (Me)

**Request:**
```bash
curl -X GET https://onesuite-backend-86225501431.asia-southeast1.run.app/api/users/auth/me/ \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

**Response:**
```json
{
  "id": 1,
  "username": "john_doe",
  "email": "john@example.com",
  "first_name": "John",
  "last_name": "Doe",
  "is_manager": false
}
```

### 3. Refresh Access Token

**Request:**
```bash
curl -X POST https://onesuite-backend-86225501431.asia-southeast1.run.app/api/users/auth/refresh/ \
  -H "Content-Type: application/json" \
  -d '{"refresh": "YOUR_REFRESH_TOKEN"}'
```

**Response:**
```json
{
  "access": "eyJ0eXAiOiJKV1QiLCJhbGc..."
}
```

### 4. Logout

**Request:**
```bash
curl -X POST https://onesuite-backend-86225501431.asia-southeast1.run.app/api/users/auth/logout/ \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"refresh": "YOUR_REFRESH_TOKEN"}'
```

**Response:**
```json
{
  "detail": "Logged out successfully."
}
```

## Authentication Flow

```
1. User logs in with credentials
   ↓
2. Server returns access + refresh tokens
   ↓
3. Client stores tokens securely
   ↓
4. Client includes access token in Authorization header for API requests
   ↓
5. When access token expires (15 min), use refresh token to get new access token
   ↓
6. On logout, send refresh token to blacklist it
```

## Security Notes

- Always use HTTPS in production (Cloud Run handles this automatically)
- Store tokens securely on the client (localStorage, httpOnly cookies, etc.)
- Refresh tokens are blacklisted on logout
- Access tokens are short-lived (15 minutes) for security
- SECRET_KEY must be kept secure and never committed to version control

## Error Responses

**Invalid Credentials:**
```json
{
  "detail": "No active account found with the given credentials"
}
```

**Expired Token:**
```json
{
  "detail": "Token is invalid or expired",
  "code": "token_not_valid"
}
```

**Missing Authorization Header:**
```json
{
  "detail": "Authentication credentials were not provided."
}
```
