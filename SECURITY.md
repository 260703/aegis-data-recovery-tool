# Security Policy

## Core Safety Guarantee: Zero Write Access

Aegis Data Recovery is built under strict forensic safety principles:

1. **Hardware Write-Block Emulation**: All disk streams (`DiskStream`) open physical targets exclusively in binary read-only mode (`'rb'`). Under no circumstances does Aegis issue write, partition, or format commands to source media.
2. **Target Collision Prevention**: The application actively compares the physical and logical device path of the recovery target against the user's selected output destination. If the output path resides on the target drive, scanning is blocked to prevent overwriting unallocated clusters.

---

## Supported Versions

| Version | Supported |
| :--- | :--- |
| v4.8.x | :white_check_mark: |
| < v4.0.0 | :x: |

---

## Reporting a Vulnerability

If you discover a security vulnerability or safety bug (e.g., an edge case where target media could be modified, or unhandled permission escalation issues):

1. **Do not open a public issue.**
2. Send an email to the project maintainers or report via GitHub Private Vulnerability Reporting.
3. Provide:
   - Operating system and Python version
   - Reproduction steps or synthetic disk image demonstrating the issue
   - Proposed fix or mitigation if available

We take all safety and security reports seriously and will acknowledge receipt within 48 hours.

