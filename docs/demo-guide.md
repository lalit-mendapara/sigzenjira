# Demo Guide — Task Classification & Extra Hours

Walkthrough for demoing everything built under
`.claude/plan/Task-Classification-Extra-Hours-development-plan.md`, with
seeded dummy data and two ready-made logins so the approval cycle can be
shown across two different users.

## 1. Seed the demo data

Run once before the demo (safe to re-run — it's idempotent, skips anything
that already exists):

```bash
bench --site mysite.in execute sigzenjira.demo.seed_demo_data.run
```

Script: `apps/sigzenjira/sigzenjira/demo/seed_demo_data.py`.

## 2. Roles in the cycle

| Role | Held by (demo user) | What it can do here |
|---|---|---|
| **Employee** | `demo.developer@sigzenjira.demo` | Raise an Additional Hours Request, submit its own Timesheets. |
| **Projects User** | `demo.developer@sigzenjira.demo` | Read/write Task, read/write/submit Timesheet. Paired with Employee on the same user — a developer needs both to actually log work. |
| **Projects Manager** | `demo.pm@sigzenjira.demo` | Approve/Reject Additional Hours Requests; has a Custom DocPerm on Task (core ERPNext ships no Task permission for this role). |
| **System Manager** | `Administrator` | Full admin — not part of the day-to-day cycle, only for setup/fixes. |

**Important:** the PM user intentionally does **not** also hold `Employee`.
ERPNext auto-scopes any Employee-role user to their own Employee record via a
User Permission row — if the approver also had Employee, they'd get scoped
down to approving only their own requests. Keep those two roles on separate
users.

Login for both: password `Demo@1234`.

## 3. What's seeded

An Epic → Story → Task → Sub-task tree ("Website Revamp"), plus two
Additional Hours Requests in different states so the whole cycle is visible
without having to build it live:

```
Website Revamp (Epic, 40h)
├── Checkout Flow (Story, 16h)
│   ├── Cart page redesign (Task, 6h)
│   │   ├── Write unit tests for cart (Sub-task)
│   │   └── Fix mobile cart layout bug (Sub-task)
│   └── Payment gateway integration (Task, 10h) — extra_hours = 4 (Approved AHR-00010)
└── Search & Filters (Story, 12h)
    ├── Filter sidebar UI (Task, 5h) — has a Pending AHR (AHR-00011, +3h) waiting for the PM
    └── Search relevance tuning (Task, 7h)
```

Extra Hours has already rolled up through Payment gateway integration (4h) →
Checkout Flow (4h) → Website Revamp (4h), so that branch demonstrates the
rollup without any clicking. The Filter sidebar UI request is left Pending
specifically so it can be approved live.

## 4. What was built (recap)

1. **Work Item Type** (`custom_work_item_type`) — mandatory Select on Task:
   Epic / Story / Task / Sub-task.
2. **Hierarchy validation** — hard-blocks the wrong parent for each type
   (e.g. a Task can't sit under an Epic).
3. **Hour budget validation** — a Story/Task's `expected_time` siblings can
   never exceed the parent's budget; blocked on save, not just warned.
   Sub-task is exempt.
4. **Additional Hours Request** doctype + workflow (Draft → Pending →
   Approved/Rejected). Only raisable against Task-type work items, enforced
   server-side even if the UI filter is bypassed. Employee can't self-approve.
5. **Approval → rollup** — approving a request adds the hours to the Task's
   `custom_extra_hours` (read-only, no_copy) and recomputes the parent Story
   and grandparent Epic as a sum of their children. Rejecting touches
   nothing, anywhere in the hierarchy.
6. **Timesheet over-budget guard** — submitting a Timesheet that would push
   a Task's Actual Time past `expected_time + custom_extra_hours` blocks the
   submit and offers **Request Additional Hours** (opens a new AHR
   pre-filled with the task). There is no bypass — the old "Submit Anyway"
   escape hatch was removed; the only way past the block is an approved
   request.

## 5. Live demo script

1. **Log in as `demo.pm@sigzenjira.demo`.** Open the Additional Hours
   Request list — show AHR-00010 (Approved) and AHR-00011 (Pending). Open
   AHR-00011, click **Approve**.
2. Open **Filter sidebar UI** (`TASK-2026-00014`) — Extra Hours is now `3`,
   and its parent **Search & Filters** Story also shows `3` (rolled up
   live).
3. **Log in as `demo.developer@sigzenjira.demo`.** Open Task
   **Payment gateway integration** — try changing `expected_time` on a
   sibling Task in the same Story so the total would exceed the Story's
   budget → save is blocked with a clear error.
4. Create a **Timesheet** logging hours against a Task near its budget
   (e.g. enough to push **Cart page redesign** past 6h) and submit — the
   over-budget dialog appears with only **Request Additional Hours**
   (no bypass). Click it, show the pre-filled AHR, submit it.
5. Switch back to the **PM** login, approve that new request, switch back
   to the developer, submit the Timesheet again — now goes through.
6. Optionally: try creating a Task directly under the Epic, or a Sub-task
   under a Story, to show hierarchy validation blocking it.

## 6. Resetting between demo runs

Re-running the seed script is safe — it skips anything already created. To
fully reset instead, delete the seeded records (Tasks under "Website
Revamp", `AHR-00010`/`AHR-00011`, the two demo Users and the Employee
record) and re-run the script.
