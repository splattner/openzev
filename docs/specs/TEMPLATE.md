# Feature Spec: <Title>

- Spec ID: SPEC-YYYY-<slug>
- Status: Draft | Approved | In Progress | Completed | Superseded
- Scope: Major | Minor
- Type: Feature | Change | Refactor
- Owners: <name(s)>
- Created: YYYY-MM-DD
- Target Release: <version/date>
- Related Issues: <links or ids>
- Related ADRs: <links or ids>
- Impacted Areas: backend | frontend | async jobs | docs | infra

---

<!--
  QUALITY STANDARD: Specs should contain enough implementation detail that a
  developer could re-implement the described feature from this document alone.
  Include exact field names, types, endpoint paths, permission classes,
  serializer shapes, frontend component names, TypeScript types, and test counts.
  See any baseline spec for reference.
-->

## 1. Problem and outcome

Describe the problem to solve and the expected business/product outcome.

## 2. Scope

### In scope

| Area | Details |
|---|---|
| <area> | <what changes> |

### Out of scope

- <item>

## 3. Actors, permissions, and ZEV scope

| Actor | Capability |
|---|---|
| `admin` | <access level> |
| `zev_owner` | <access level> |
| `participant` | <access level> |

Include backend permission classes and frontend `ProtectedRoute` roles.

## 4. Data model

<!--
  For each model affected, include:
  - Field table (name, type, constraints, default)
  - Key methods and their behavior
  - Validation logic (clean/save overrides)
  - Ordering, constraints, indexes
  - Serializer fields (including read-only)
-->

### 4.x <ModelName>

**Model:** `<app>.models.<ModelName>`

| Field | Type | Default | Constraints / Notes |
|---|---|---|---|
| `<field>` | <type> | <default> | <notes> |

**Serializer:** `<SerializerName>` — fields: `<list>` (read-only: `<list>`).

## 5. API contracts

<!--
  For each endpoint, include:
  - Full path, HTTP methods
  - Permission class or manual permission check
  - Request/response shapes
  - Error behavior and status codes
  - View class or function name
-->

| Endpoint | Method | Permission | Behaviour |
|---|---|---|---|
| `/api/v1/<path>/` | GET | `<PermissionClass>` | <description> |

## 6. Async and integration behavior

<!--
  For Celery tasks, include: task name, bind/retry config, what triggers them,
  error handling/fallback behavior. For external integrations (email, PDF, imports),
  describe the rendering pipeline and dependencies on settings/models.
-->

- <task or integration description>

## 7. Frontend

<!--
  For each page/component, include:
  - File path
  - TanStack Query key and queryFn
  - Key UI elements and user interactions
  - Mutation functions and cache invalidation
  - Route path and ProtectedRoute roles
-->

### 7.x <PageName>

**File:** `frontend/src/pages/<PageName>.tsx`

- Route: `/<path>`
- Query: `useQuery({ queryKey: ['<key>'], queryFn: <fn> })`
- <UI and interaction description>

### TypeScript types

**File:** `frontend/src/types/api.ts`

```typescript
// Include exact interface definitions for new/changed types
interface <TypeName> {
    <field>: <type>
}
```

### API client functions

**File:** `frontend/src/lib/api.ts`

| Function | Method | Endpoint |
|---|---|---|
| `<functionName>()` | GET | `/<path>/` |

## 8. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| <risk> | High / Medium / Low | <mitigation> |

## 9. Test plan

<!--
  List test classes with exact test method names and what they assert.
  Include test counts per class. For backend, reference the file path.
  For frontend, describe build/type-check validation.
-->

### Backend — `<app>/tests.py`

**`<TestClassName>`** (<N> tests):

| Test | Asserts |
|---|---|
| `test_<name>` | <what is verified> |

### Frontend

- Build and type checks: `npm run build`
- <interaction tests if applicable>

### Acceptance criteria

- [ ] <criterion — specific, verifiable>
- [ ] <criterion>
- [ ] <criterion>
