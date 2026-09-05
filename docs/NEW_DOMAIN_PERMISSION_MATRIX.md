# New Domain Permission Matrix

| Domain | Permission | Purpose |
|---|---|---|
| Supplier rate | `supplier_rate.view` | Read agreement APIs/screens |
| Supplier rate | `supplier_rate.create` | Create/edit/submit drafts |
| Supplier rate | `supplier_rate.approve` | Approve and activate |
| Supplier rate | `supplier_rate.override` | Supply approved variance override reason |
| Production log | `production_log.view` | Read shift logs |
| Production log | `production_log.create` | Create/edit drafts |
| Production log | `production_log.submit` | Submit drafts |
| Production log | `production_log.approve` | Approve and lock |
| Customer | `customer.view` | Read customer master |
| Customer | `customer.create` | Create customers/addresses |
| Customer | `customer.edit` | Edit customers/addresses |
| Customer | `customer.block` | Block/unblock customers |
| Scheduler | `scheduled_task.view` | Read task configuration/logs |
| Scheduler | `scheduled_task.run` | Run safe jobs manually |
| Scheduler | `scheduled_task.configure` | Configure schedule metadata |
| Reports | `report.supplier_rate` | Supplier-rate reports/CSV |
| Reports | `report.production_log` | Production-log reports/CSV |
| Reports | `report.customer_master` | Customer reports/CSV |
| Reports | `report.scheduled_task` | Scheduler reports/CSV |

Owner and Admin receive all permissions. Purchase, Production, Data Entry, Sales, and Auditor groups receive least-privilege subsets from `seed_erp_roles`.
