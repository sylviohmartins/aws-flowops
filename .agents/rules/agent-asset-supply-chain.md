# Third-party agent asset supply chain

Do not install/copy a skill, MCP, plugin, hook, agent, harness or prompt merely because it is popular.

Minimum review:

`DISCOVER -> SOURCE_VERIFY -> LICENSE -> STATIC_REVIEW -> PERMISSIONS -> MATURITY -> SANDBOX -> DECISION`

Evaluate provenance, license, maintenance, filesystem/shell/network/secret permissions, install/postinstall behavior, dynamic downloads, prompt-injection/exfiltration risk, transitive dependencies, overlap with existing capabilities and whether a smaller local adaptation is safer.

Classify useful architecture that should not be imported as `ADAPT`. Rankings/stars/download counts are discovery signals, never authorization. Avoid tool soup: required-path additions need demonstrated incremental value.
