---
name: supabase-dual-auth-dotnet
description: Integrate Supabase Auth into an existing .NET backend with custom JWT auth. Covers RLS migration with dual-auth fallback, dual JWT validation handler for .NET, self-hosted Supabase (gotrue + kong) via Docker Compose, and Flutter Supabase initialization.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [Supabase, Auth, .NET, JWT, RLS, PostgreSQL, DSGVO]
    related_skills: [github-issues]
---

# Supabase Dual Auth for .NET Backends

Migrate a custom-JWT .NET backend to support **both** Supabase Auth (from mobile apps) and custom JWT auth (from server-side) — with full Row Level Security and DSGVO-compliant multi-region support.

## When to use this skill

- You have a .NET backend with its own JWT auth (`users` + `refresh_tokens` tables)
- You want to add Supabase Auth (Flutter mobile app) **without** breaking existing auth
- You need RLS (Row Level Security) that works with both auth systems
- You want self-hosted Supabase (gotrue) for DSGVO compliance (Frankfurt region)

## Architecture

```
Flutter App               .NET Backend
┌────────────┐            ┌──────────────────┐
│ Supabase   │ ──JWT──▶   │ Dual Auth Handler │
│ Auth       │            │ ┌──────────────┐ │
└────────────┘            │ │ Supabase JWT  │ │
                          │ │ Custom JWT    │ │
Server/Admin              │ └──────────────┘ │
┌────────────┐            └──────────────────┘
│ Custom JWT │ ──JWT──▶           │
└────────────┘                     ▼
                          ┌──────────────────┐
                          │  PostgreSQL RLS   │
                          │  (fitspar_curr..) │
                          └──────────────────┘
```

## Implementation Steps

### Step 1: Create RLS migration with dual-auth helper

Create a SQL migration (e.g., `004_supabase_rls.sql`) with:

```sql
-- Helper: gets user ID from Supabase auth OR custom JWT context
CREATE OR REPLACE FUNCTION fitspar_current_user_id()
RETURNS UUID LANGUAGE plpgsql STABLE AS $$
DECLARE uid UUID;
BEGIN
  -- Try Supabase Auth (auth.uid from gotrue)
  BEGIN uid := auth.uid(); IF uid IS NOT NULL THEN RETURN uid; END IF;
  EXCEPTION WHEN OTHERS THEN NULL;
  END;
  -- Fallback: custom JWT (set via SET app.current_user_id)
  BEGIN uid := current_setting('app.current_user_id', TRUE)::UUID; RETURN uid;
  EXCEPTION WHEN OTHERS THEN RETURN NULL;
  END;
END;
$$;

-- Helper: check if request is authenticated (either system)
CREATE OR REPLACE FUNCTION fitspar_is_authenticated()
RETURNS BOOLEAN LANGUAGE plpgsql STABLE AS $$
BEGIN
  BEGIN IF auth.role() = 'authenticated' THEN RETURN TRUE; END IF;
  EXCEPTION WHEN OTHERS THEN NULL;
  END;
  BEGIN IF current_setting('app.current_user_id', TRUE) IS NOT NULL THEN RETURN TRUE; END IF;
  EXCEPTION WHEN OTHERS THEN RETURN FALSE;
  END;
  RETURN FALSE;
END;
$$;
```

**RLS Policy pattern** (user sees own data):

```sql
CREATE POLICY "table_name_own" ON profiles
  FOR ALL
  USING (user_id = fitspar_current_user_id())
  WITH CHECK (user_id = fitspar_current_user_id());
```

**Public read-only** (offers, recipes):

```sql
CREATE POLICY "table_name_public_read" ON offers
  FOR SELECT USING (true);
```

### Step 2: Dual JWT auth handler (.NET)

Create `Auth/SupabaseAuthConfig.cs`:

```csharp
public static class SupabaseAuthConfig
{
    public static void AddDualAuthentication(this IServiceCollection services, IConfiguration configuration)
    {
        var jwtSettings = configuration.GetSection("Jwt").Get<JwtSettings>()!;
        var supabaseJwtSecret = configuration["Supabase:JwtSecret"] ?? configuration["SUPABASE_JWT_SECRET"];

        services.AddAuthentication(options =>
        {
            options.DefaultAuthenticateScheme = "Dual";
            options.DefaultChallengeScheme = "Dual";
        })
        .AddPolicyScheme("Dual", "Dual Auth (Custom + Supabase)", options =>
        {
            options.ForwardDefaultSelector = context =>
            {
                var authHeader = context.Request.Headers["Authorization"].FirstOrDefault();
                if (authHeader?.StartsWith("Bearer ") == true)
                {
                    var token = authHeader["Bearer ".Length..].Trim();
                    try
                    {
                        var parts = token.Split('.');
                        if (parts.Length == 3)
                        {
                            var payload = DecodeBase64Url(parts[1]);
                            // Supabase tokens have "role" and "iss" claims
                            if (payload.Contains("\"role\"") && payload.Contains("supabase"))
                                return "Supabase";
                        }
                    }
                    catch { }
                }
                return "Custom";
            };
        })
        .AddJwtBearer("Custom", options => { /* existing custom JWT validation */ });

        if (!string.IsNullOrEmpty(supabaseJwtSecret))
        {
            services.AddAuthentication()
                .AddJwtBearer("Supabase", options =>
                {
                    var supabaseKey = Encoding.UTF8.GetBytes(supabaseJwtSecret);
                    options.TokenValidationParameters = new TokenValidationParameters
                    {
                        ValidateIssuerSigningKey = true,
                        IssuerSigningKey = new SymmetricSecurityKey(supabaseKey),
                        ValidateIssuer = false,
                        ValidateAudience = false,
                        ValidateLifetime = true,
                        ClockSkew = TimeSpan.FromMinutes(2),
                        NameClaimType = "sub",
                        RoleClaimType = "role"
                    };
                });
        }
    }
}
```

In `Program.cs`, replace the old single-scheme auth:

```csharp
// Replace: builder.Services.AddAuthentication(JwtBearerDefaults.AuthenticationScheme)...
// With:
builder.Services.AddDualAuthentication(builder.Configuration);
```

### Step 3: Self-hosted Supabase (Docker Compose)

Create `docker/docker-compose.supabase.yml`:

```yaml
services:
  gotrue:
    image: supabase/gotrue:v2.157.0
    container_name: fitspar-gotrue
    ports:
      - "127.0.0.1:9999:9999"
    env_file:
      - ./supabase/gotrue.env
    environment:
      GOTRUE_API_HOST: 0.0.0.0
      GOTRUE_API_PORT: 9999
    depends_on:
      postgres:
        condition: service_healthy
    networks:
      - fitspar-internal

  kong:
    image: kong:3.6
    container_name: fitspar-kong
    ports:
      - "127.0.0.1:8000:8000"
    environment:
      KONG_DATABASE: "off"
      KONG_DECLARATIVE_CONFIG: /etc/kong/kong.yml
    volumes:
      - ./supabase/kong.yml:/etc/kong/kong.yml:ro

networks:
  fitspar-internal:
    external: true
```

**Gotrue env** (`docker/supabase/gotrue.env`):

```env
GOTRUE_SITE_URL=http://localhost:8085
GOTRUE_JWT_SECRET=<generated-secret>
DATABASE_URL=postgresql://fitspar:fitspar_dev_change_me@postgres:5432/fitspar?sslmode=disable
GOTRUE_EXTERNAL_EMAIL_ENABLED=true
GOTRUE_DISABLE_SIGNUP=false
GOTRUE_MAILER_AUTOCONFIRM=false
```

### Step 4: Flutter Supabase initialization

In `main.dart`:

```dart
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await dotenv.load(fileName: '.env');

  const supabaseUrl = String.fromEnvironment(
    'SUPABASE_URL',
    defaultValue: 'http://localhost:54321',
  );
  const supabaseAnonKey = String.fromEnvironment(
    'SUPABASE_ANON_KEY',
    defaultValue: '',
  );

  final resolvedUrl = supabaseUrl == 'http://localhost:54321'
      ? dotenv.env['SUPABASE_URL'] ?? supabaseUrl
      : supabaseUrl;
  final resolvedKey = supabaseAnonKey.isEmpty
      ? dotenv.env['SUPABASE_ANON_KEY'] ?? supabaseAnonKey
      : supabaseAnonKey;

  if (resolvedKey.isNotEmpty) {
    await Supabase.initialize(url: resolvedUrl, anonKey: resolvedKey);
  }

  runApp(const ProviderScope(child: FitSparApp()));
}
```

### Step 5: Environment configuration

Add to `.env.example`:

```env
SUPABASE_URL=http://localhost:54321
SUPABASE_ANON_KEY=
SUPABASE_SERVICE_KEY=
SUPABASE_JWT_SECRET=
```

## Pitfalls

1. **Auth detection order matters**: Try `auth.uid()` first, fall back to `current_setting()`. If reversed, Supabase context may be overwritten.
2. **Supabase JWT has no `aud` claim**: Set `ValidateAudience = false` in JWT validation parameters.
3. **Kong required for Supabase client**: The Flutter `supabase_flutter` package expects the Kong API gateway at port 8000 for auth routes. Without Kong, configure the URL to point directly to gotrue (port 9999).
4. **Migration order**: Apply RLS migration **after** base schema migrations. The tables and `auth` schema must exist first.
5. **Token expiry**: Supabase tokens expire after 1 hour by default. The Flutter supabase_flutter package handles auto-refresh. Your custom JWT system needs its own refresh flow.
6. **DSGVO region**: If using Supabase Cloud, select Frankfurt (eu-central-1) during project creation — it cannot be changed later.
7. **Service role**: Use `SUPABASE_SERVICE_KEY` (not anon key) for server-side operations that bypass RLS.

## Verification

```bash
# 1. Apply migration
docker exec -i fitspar-postgres psql -U fitspar -d fitspar < database/migrations/004_supabase_rls.sql

# 2. Check RLS is enabled
docker exec fitspar-postgres psql -U fitspar -d fitspar -c "
  SELECT tablename, rowsecurity FROM pg_tables
  WHERE schemaname='public' AND rowsecurity = true;"

# 3. Test: anon user sees no profiles
docker exec fitspar-postgres psql -U fitspar -d fitspar -c "
  SET ROLE anon; SELECT count(*) FROM profiles;"

# 4. Test: authenticated user sees own data (via app context)
docker exec fitspar-postgres psql -U fitspar -d fitspar -c "
  SET app.current_user_id TO '<valid-uuid>'; SELECT * FROM profiles;"

# 5. Gotrue health
curl -s http://localhost:9999/health

# 6. Start everything
docker compose -f docker/docker-compose.yml -f docker/docker-compose.supabase.yml up -d
```
