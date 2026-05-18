---
title: Workflow Catalog Group
description: "The Workflow Catalog group is focused on developing Workflow Catalog, a catalog of AI Agents, tools, and workflows that can be created, curated, and shared across organizations, groups, and projects."
---

## Vision

The Workflow Catalog group is focused on developing Workflow Catalog, a catalog of AI Agents, tools, and workflows that can be created, curated, and shared across organizations, groups, and projects.

## Team members

**Engineering Manager & Engineers**

{{< team-by-manager-slug "sam-beckham" >}}

## How to reach us

Depending on the context here are the most appropriate ways to reach out to the Workflow Catalog group:

* Slack Channel: `#g_workflow_catalog`
* GitLab group `@gitlab-org/ai-powered/workflow-catalog/engineering` (just engineers)

## How we work

We're just getting started and will be defining how we work as we settle in to the new team.
Here are some links to get us started:

* [Root Epic](https://gitlab.com/groups/gitlab-org/-/epics/11111): For grouping all the work and setting out a roadmap
* [Issue board](https://gitlab.com/groups/gitlab-org/-/boards/3871464): For all in-flight issues
* [Team tasks](https://gitlab.com/gitlab-org/ai-powered/workflow-catalog/team-tasks/-/issues): For all non-product related team issues
* [Async updates](https://gitlab.com/gitlab-org/ai-powered/workflow-catalog/team-tasks/-/issues/?label_name%5B%5D=async%20update)

### Communication

The Workflow Catalog Team communicates based on the following guidelines:

* Always prefer async communication over sync meetings.
* Don't shy away from arranging a [sync call](/handbook/communication/#video-calls) when async is proving inefficient, however always record it to share with team members.
* By default communicate in the open.
* Prefer public channels (`#g_workflow_catalog`) over private message for work-related Slack messaging.

### Frontend-Backend collaboration

We aim to foster high levels of collaboration between frontend and backend engineers to ensure
development velocity and code quality.

* **Schema-first development**: Before implementation begins, frontend and backend engineers collaborate
  to design a GraphQL API schema based on UI requirements, user experience needs, and performance considerations.
* **Parallel development processes**: Once the schema is agreed upon, the frontend can proceed
  using mock data, mock endpoints, or API stubs that match the agreed schema. The backend can
  focus on implementing the data model, business logic, and actual API schema.
* **Maintaining alignment**: We value great communication. When requirements or schema need to change, we communicate
  early through the relevant GitLab issue or in [`#g_workflow_catalog`](https://gitlab.enterprise.slack.com/archives/C08T5J1KXKQ)
  so our frontend or backend counterparts stay informed of all changes and can provide feedback early to avoid late-stage blockers.

### AI stage collaboration

The Workflow Catalog relies on the
[Workflow Service](https://gitlab.com/gitlab-org/modelops/applied-ml/code-suggestions/ai-assist/-/tree/main/duo_workflow_service?ref_type=heads)
as a foundational backend service.
Most Workflow Catalog features require new capabilities to be developed within Workflow Service,
which means our engineers will need to contribute directly to that codebase in partnership with the
[Duo Agent Platform team](../duo-agent-platform/_index.md).

**Collaboration Requirements:**

* All Workflow Service contributions must be developed in close partnership with the Duo Agent Platform team
* Our implementations must align with their service architecture and vision
* We commit to supporting Workflow Service's broader goals and adhering to their technical standards

**Collaboration Process:**

* Reach out to relevant Duo Agent Platform contacts (listed below) during the planning phase
* Join their [`#g_duo_workflow`](slack://channel?id=g_duo_workflow) channel
* Follow our [async communication preferences](#communication) by default, but schedule sync meetings
  when needed and ensure key outcomes are documented in GitLab issues

#### Primary Duo Agent Platform contacts

| Team Member | Expertise Area |
| ---      | ---     |
| [Mikołaj Wawrzyniak](https://gitlab.com/mikolaj_wawrzyniak) | Workflow Service architecture |
| [Frédéric Caplette](https://gitlab.com/f_caplette) | Client-side implementation |
| [Dylan Griffith](https://gitlab.com/DylanGriffith) | Workflow Executor architecture: remote execution environment and runner implementation |
| [Jessie Young](https://gitlab.com/jessieay) | Authorization and authentication |
| [Shekhar Patnaik](https://gitlab.com/shekharpatnaik)  / [Igor Drozdov](https://gitlab.com/igor.drozdov) | Duo Chat agent integration |
| [Sebastian Rehm](https://gitlab.com/bastirehm) | Engineering Manager, backup contact for any of the above |

### Our tech stack

* GraphQL [backend](https://docs.gitlab.com/development/api_graphql_styleguide/) and
  [frontend](https://docs.gitlab.com/development/fe_guide/graphql/). All new schema items must be
  [marked experimental](https://docs.gitlab.com/development/api_graphql_styleguide/#mark-schema-items-as-experiments)
  to let us making breaking changes when we need.
* GraphQL [subscriptions](https://docs.gitlab.com/development/fe_guide/graphql/#subscriptions) rather than polling.

## Team meetings

### Workflow Catalog: Group meeting

* **Time**: Every Tuesday at 05:30 UTC and 10:00 UTC. It's held twice in one day to allow APAC and EMEA to attend.
* **Purpose**: This meeting serves as a general sync meeting to bring up any current issues and blockers.
* **Agenda**: [Google Doc (internal only)](https://docs.google.com/document/d/19zrzqN37ZVwwEJ9iYhy4QBsUzVN0Hd1j1yn8J0v4dqE)
* **Recordings**: [Google Drive (internal only)](https://drive.google.com/drive/folders/1I9s96jg9knqOwDLabhn9100H-MsvG2ne)

## Capacity planning

We use a lightweight system of issue weighting to help with capacity planning.
These weights help us ensure that the amount of scheduled work in a cycle is
reasonable, both for the team as a whole and for each individual. The "weight
budget" for a given cycle is determined based on the team's recent output, as
well as the upcoming availability of each engineer.

Since [things take longer than you think](https://erikbern.com/2019/04/15/why-software-projects-take-longer-than-you-think-a-statistical-model.html),
it's OK if an issue takes longer than the weight indicates. The weights are
intended to be used in aggregate, and what takes one person a day might take
another person a week, depending on their level of background knowledge about
the issue. **That's explicitly OK and expected.** We should strive to be
accurate, but understand that they are estimates!  Change the weight if it is
not accurate or if the issue becomes harder than originally expected. Leave a
comment indicating why the weight was changed and tag your EM so that we can
better understand weighting and continue to improve.

### Weights

The weights we use are:

| Weight | Description  |
| --- | --- | --- |
| 1: Trivial | The problem is very well understood, no extra investigation is required, the exact solution is already known and just needs to be implemented, no surprises are expected, and no coordination with other teams or people is required.<br><br>Examples are documentation updates, simple regressions, and other bugs that have already been investigated and discussed and can be fixed with a few lines of code, or technical debt that we know exactly how to address, but just haven't found time for yet. |
| 2: Small | The problem is well understood and a solution is outlined, but a little bit of extra investigation will probably still be required to realize the solution. Few surprises are expected, if any, and no coordination with other teams or people is required.<br><br>Examples are simple features, like a new API endpoint to expose existing data or functionality, or regular bugs or performance issues where some investigation has already taken place. |
| 3: Medium | Features that are well understood and relatively straightforward. A solution will be outlined, and most edge cases will be considered, but some extra investigation will be required to realize the solution. Some surprises are expected, and coordination with other teams or people may be required.<br><br>Bugs that are relatively poorly understood and may not yet have a suggested solution. Significant investigation will definitely be required, but the expectation is that once the problem is found, a solution should be relatively straightforward.<br><br>Examples are regular features, potentially with a backend and frontend component, or most bugs or performance issues. |
| 5: Large | Features that are well understood, but known to be hard. A solution will be outlined, and major edge cases will be considered, but extra investigation will definitely be required to realize the solution. Many surprises are expected, and coordination with other teams or people is likely required.<br><br>Bugs that are very poorly understood, and will not have a suggested solution. Significant investigation will be required, and once the problem is found, a solution may not be straightforward.<br><br>Examples are large features with a backend and frontend component, or bugs or performance issues that have seen some initial investigation but have not yet been reproduced or otherwise "figured out". |

Anything larger than 5 should be broken down if possible.

Weights should account for both development and review time.

Security issues are typically weighted one level higher than they would normally
appear from the table above. This is to account for the extra rigor of the
[patch release process](https://gitlab.com/gitlab-org/release/docs/blob/master/general/security/engineer.md).
In particular, the fix usually needs more-careful consideration, and must also
be backported across several releases.
