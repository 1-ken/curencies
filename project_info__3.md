Postman itself does **not** create the token. You need to obtain the JWT from your **NextAuth login flow** or from a frontend token endpoint, then paste it into Postman as a Bearer token.

## What the backend expects
From `app/core/auth.py`, the token must be:

- signed with `NEXTAUTH_SECRET`
- using `HS256`
- contain `sub`
- contain `exp`

That means it is a **NextAuth-compatible JWT**, not just any session value.

## Where to get it
Check one of these places in your Next.js app:

1. **A custom token endpoint**
   - Your logs mention `/api/observer/ws-token`
   - That may be the route that returns the observer token for this backend

2. **Browser storage / cookies**
   - DevTools → Application
   - Check cookies, local storage, or session storage for a JWT-like value

3. **NextAuth session/token callbacks**
   - If your app exposes the token through a callback, that is the value you need

## In Postman
Once you have the token:

- Go to **Authorization**
- Choose **Bearer Token**
- Paste the JWT
- Send the request again

Example:

```http
Authorization: Bearer eyJhbGciOi...
```

## If you can’t find a token
For local testing only, set:

```env
AUTH_DISABLED=true
```

Then the backend will stop returning `401` and will accept requests without a token.

## Important
If `/api/auth/session` only shows user info, that may **not** be the raw JWT your FastAPI backend wants. The backend wants the actual signed token, not just the session JSON.

If you want, I can help you locate the exact token source in your Next.js app.