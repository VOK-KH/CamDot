# job.json schema

Path: `.cursor/job.json`

```json
{
  "version": 1,
  "manager": "cto",
  "policy": {
    "max_parallel": 3,
    "auto_start": false,
    "update_status": true
  },
  "jobs": [
    {
      "id": "JOB-001",
      "title": "Short title",
      "assignee": "gui-engineer",
      "status": "pending",
      "priority": 1,
      "depends_on": [],
      "files": ["app/gui/"],
      "prompt": "Full task for the subagent.",
      "acceptance": ["Observable done condition"],
      "notes": "",
      "updated_at": "2026-09-14T00:00:00Z"
    }
  ]
}
```

`status`: `pending` | `assigned` | `in_progress` | `blocked` | `done` | `cancelled`

`priority`: `1` is highest. `depends_on` is a list of other job ids.
