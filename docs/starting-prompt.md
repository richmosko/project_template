# Opening Prompt
I would like to come up with a template for new projects such that each new project I start has a consistent process and starter skills and team roles. I want to run each project with an AGILE mindest, and break down the overall project phases as follows:
Research --> Plan --> Implement --> Validate

## Research
This is the phase where claude and I work with eachother to discuss what the project roughly is and what is possible. Claude also validates and refines the workflow that will be used and generates an initail PRD document. UX/UI Design is a late part of this phase. SecOps is consulted here at a very high level simply to define sec features and regulatory considerations for later. Initial team roles are also defined here.

## Plan
This phase focuses on the How we will build / deploy / deliver the project. Come up with the Architecture and Infrastructure. What are the CI/CD deployment schemes. How do we break down the full task into managable chuncks that can be sprinted? If this is an extension of an existing project or workflow, then what is the Integration plan and scope? What are the security requirements and how are they validated? Claude works with the user to define these things and generates Architecture and Security Documents. WORKFLOW document gets updated with findings.

## Implement
This is doing the actual developemnt work. Unit deliverable verification goes here as well. Remember that we want to chumk the work into bite sized pieces for sprint deliverables... This also helps with context window managment. If processes or tasks repeat 2 or more times then these tasks should be defined as skills and offloaded.

## Validate
Implement and Validate are nested and tightly interconnected loops. The overall project is an Implement-->Validate loop. Within it are version and milestone Implement-->Validate loops. And within that are feature Implement-->Validate loops. Things should be Test Driven: Write failing/passing tests first, followed by the actual implementation, and then confirm that tests pass. Version control is non-negotialble. At least git locally, and GitHub for cloud and/or public repositories. Google docs/sheets/etc. should tag versions in versioning as well. Commits should happen regularly, with push+PR for each completed I/V (Implement-->Validate) loop.

# Artifacts
To start we should have the following Artifacts in each project (everything under revision control):
- CLAUDE.md: Automatically read and self explanitory. You can work with me to define what needs to live in here.
- WORKFLOW.md: States the "How" of running the project. Defines the Phased approach above, and how steps along the way are defined. Defines the roles of the User (human), team-lead (top level agent), and team roster (team-agents). Defines what the artifacts are and where they are located.
- MILESTONES.md: Current development and workflow state. What are all the milestones? What are the enumerated steps and sprints along the way? Where are we along this roadmap right now (completed, in-progress, backlogged, etc.)? What decisions did we make along the way (stored in appendix)? We should brainstorm on what's the best way to do this... But I'd like for this to tie into a task/ticket managment system like Linear.
- docs/PRD.md or docs/PRD.html: Product Requirement Document. This should be lightweight and AGILE grounded. Features will change as new information is gathered. To be expected. To seed this PRD we should build a skill or "generate-prd.md" file that sets an outline and prompts the user with questions for how to write the PRD. I want this to follow the guidelines of a real PM who has experience with AI: https://www.chatprd.ai/learn/prd-template
- docs/ARCH.md or docs/ARCH.html: Architecture and Infrastructure Docuemnt. Defines how features will get implemented. What are the tech stacks that will be used. Flowcharts. Diagrams. etc. This could use some reasearch from you to help me flesh this out... but we should have a started skill or "generate-archdoc.md" file for consistency.
- docs/SECURITY.md or docs/SECURITY.html: Security Requirements Docuemnt. Input from SecOps for security considerations and requirements. Also could use some reaserch from you to help me flesh this out... but we should have a starter skill or "generate-secdoc.md" file for consistency.
- .claude/settings.json: mostly as a starting point for defining hooks for which files to read upon starting a new session
- .gitignore: defines what to ignore for commiting files to git

# Skills
TBD... but at a bare minimum we need skills to:
- add and commit files
- create development branches and push to GitHub + create Pull Requests (PR)
- merge PRs back to main
- open markdown or html files for human viewing via command line

# Managing Context Windows
Somewhere in the CLAUDE.md file we need to keep track of context windows and provide suggestions to the user when it would be a good time to consolidate important context and perhaps start a new session from scratch. The human in the loop is asynchronous... so there will be long gaps in time between interactions. And potentially the scope of the project could be large, so we will need the ability to start anywhere along the project development on a fresh session. So storing the current state spmewhere is critical.

# Other Notes
- Preference to use claude team-agents and all current features of it
- Preference to use Linear (and its MCP) to track tasks if possible
- Preference to have human readable and contextually concise product and architectural documents. Documents that link to and reference other documents are totally fine. If it is possible to maintain these documents in html for better readability, visuals, and interactivity... so much the better.