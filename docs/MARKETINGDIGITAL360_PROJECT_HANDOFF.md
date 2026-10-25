# MarketingDigital360 — project handoff

Updated 24 October 2026.

## Identity and scope

MarketingDigital360 is PAC DIGITALE's planned social-media intelligence and
analytics platform. It is a product project, distinct from the former
``Marketing Digital`` campaign-work folder. Campaign evidence, budgets and
Meta operations do not define the MarketingDigital360 project.

## Current implementation

There is not yet a standalone application repository or runtime. The current
versioned implementation is the PAC DIGITALE WordPress custom-theme repository:

- repository: `https://github.com/lyz5/pacdigitalewebsite.git`;
- local source: `C:\Users\diagnepa\Documents\Personal Projects\Website`;
- branch: `main`;
- public landing page: `https://www.pacdigitale.com/marketingdigital360/`;
- legal pages: `/marketingdigital360/terms/` and
  `/marketingdigital360/privacy/`.

The landing page is deployed and describes the product as under development.
It is not evidence that Facebook, Instagram, TikTok or LinkedIn integrations
are implemented or authorized.

## Product direction

The planned scope is authorized, official-API social-media analytics and
management: audience intelligence, content and campaign performance,
executive dashboards and AI-assisted insights. Users must retain control of
account permissions and revocation.

## Protections

- A future platform needs its own repository, local runtime, configuration and
  deployment target before it can be treated as an independent application.
- Do not store platform access tokens, OAuth secrets, advertising-account data
  or user data in documentation, Git or Dropbox.
- Connecting a social platform, importing data, publishing content, changing a
  campaign or spending budget each requires explicit authorization.
- The current WordPress deployment follows the Website project's controlled
  theme workflow; it is not authorization to deploy a future analytics app.
