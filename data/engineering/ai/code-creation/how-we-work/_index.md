---
title: "How We Work"
description: "Working processes, communication practices, and operational procedures for the Code Creation group"
---

## Introduction

Welcome to the Code Creation group's working processes guide. This handbook page outlines how our team operates on a day-to-day basis, including our communication channels, issue tracking, development workflows, and milestone planning processes. 

We're a globally distributed team working on AI-powered code creation features, and we've developed these practices to ensure clear communication, transparency, and effective collaboration across time zones. These processes help us maintain alignment with our goals while providing the flexibility needed for innovation and problem-solving.

This page serves as both an onboarding resource for new team members and a reference for existing team members to ensure consistency in our workflows. If you have questions about any of these processes, please reach out in our Slack channel (#g_code_creation).

## Commonly Monitored Issue Lists

- [Planning Issues](https://gitlab.com/gitlab-org/create-stage/-/issues/?sort=due_date&state=opened&label_name%5B%5D=group%3A%3Acode%20creation&label_name%5B%5D=Planning%20Issue&first_page_size=20)
- [Issue board - by workflow](https://gitlab.com/groups/gitlab-org/-/boards/5998095)
- [Issue board - by project](https://gitlab.com/groups/gitlab-org/-/boards/9406346)
- [Issue board - by iteration](https://gitlab.com/groups/gitlab-org/-/boards/9413038)
- [Reliability](https://gitlab.com/gitlab-org/gitlab/-/boards/4227439?label_name[]=group%3A%3Acode%20creation)
- [Security](https://gitlab.com/gitlab-org/gitlab/-/issues/?sort=due_date&state=opened&label_name%5B%5D=security&label_name%5B%5D=group%3A%3Acode%20creation&first_page_size=20)
- [InfraDev Issues](https://gitlab.com/gitlab-org/gitlab/-/issues/?sort=due_date&state=opened&label_name%5B%5D=devops%3A%3Acreate&label_name%5B%5D=infradev&label_name%5B%5D=group%3A%3Acode%20creation&amp;not%5Blabel_name%5D%5B%5D=type%3A%3Afeature&amp;not%5Blabel_name%5D%5B%5D=severity%3A%3A4&first_page_size=200)

## Engineering Onboarding

To help get started as a developer with the Code Creation team, we have created an
[onboarding issue template](https://gitlab.com/gitlab-org/ai-engineering/code-creation/team-tasks/-/issues/new?issuable_template=developer_onboarding).

## Time Off

Team members should add any [planned time off](/handbook/people-group/paid-time-off/#paid-time-off) in the “Workday” slack app, in accordance with the [taking time off](/handbook/engineering/#taking-time-off) policy, including creating a [PTO coverage issue](https://gitlab.com/gitlab-com/engineering-division/pto-coverage/-/issues/new).

## Milestone Meetings

Our team operates on monthly milestones with one key meeting per milestone cycle. This meeting combines both the retrospective for the previous milestone and the kickoff for the upcoming milestone. To accommodate our globally distributed team, this meeting is held twice each milestone at different times - once in an APAC-friendly time zone and once in an EMEA/AMER-friendly time zone. This approach ensures all team members have the opportunity to participate live in the meeting that best fits their schedule.

The Combined Retrospective/Kickoff Meeting serves two purposes: reviewing the outcomes from our async retrospectives of the completed milestone, and aligning on objectives, discussing requirements, and assigning responsibilities for the upcoming milestone.

All of our meetings are recorded and uploaded to the [Code Creation YouTube Playlist](https://www.youtube.com/playlist?list=PL05JrBw4t0KoZOUC-DfaJOzFb6w6hG198). Some meetings are marked as private, so internal team members will need to switch to use the [Unfiltered YouTube account](/handbook/marketing/marketing-operations/youtube/#unable-to-view-a-video-on-youtube).

## Milestone Planning

See the [Code Creation Milestone Planning](/handbook/engineering/ai/code-creation/how-we-work/milestone_planning/) for more information on the milestone planning process.

## Weekly Status Updates

We maintain a practice of weekly async status updates to ensure clear communication, track progress effectively, and maintain transparency across our team. This process aligns with our core values by fostering collaboration, driving results, and promoting efficiency through structured communication.

### Timing and Frequency

- Team members post updates every Wednesday
- Updates are required for all assigned issues
- Multiple updates may be needed if working on multiple issues

### Template

This is the template to use for the updates

```markdown
## Async Status Update yyyy-mm-dd

- **Progress & Status**: _What progress have you made? What's the current state?_
- **Next Steps**: _What are your planned next actions?_
- **Blockers**: _Are you blocked or need assistance with this?_
- **How confident are you that this will make it to the current milestone?**
    - [ ] Not confident
    - [ ] Slightly confident
    - [ ] Very confident

_Remember to update the workflow label!_

/cc @mnohr @jordanjanes
```

Be sure to tag the engineering manager, product manager, and any team members you are collaborating with.

### Best practices

- Be specific and concise in updates
- Always include next steps, even if they're tentative
- Flag blockers early - don't wait until they become critical
- Use the template consistently for easier scanning
- Link to relevant issues or documentation when appropriate
