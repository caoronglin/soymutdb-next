# ADR-0009: retire the page builder and the widget system

Status: accepted
Context: the React portal composed its public pages from `page_definitions`
(a stored component tree) and rendered widgets in named slots. Publishing
content therefore meant authoring a page definition, and the admin console
carried a page-builder editor, a widget registry, a widget editor, a layout
editor, a preview route and a health page to support that.

The Vue portal does not consume either: it renders fixed, tested routes
(gene/mutant/variant/analytics/…), and its content comes from the records
(news, publications) and the settings-driven site sections (about/home/footer).
After the cutover, `page_definitions` and the widget registry had exactly one
consumer left — the admin's own preview.

Decision: the page builder and the widget system are retired from the admin
console. Their tables and API endpoints remain (deleting stored data is a
separate, audited migration), but nothing in the product reads or writes them
any more.

Consequences:

* an operator can no longer compose a public page from components. Adding a
  route is a code change with a test, which is what the database-first contract
  asks for: "marketing or editorial content may support these workflows but must
  not displace them".
* the admin console loses the page-builder, widget, layout and widget-health
  routes together with their editors. That removes a large surface that had one
  consumer.
* the `page_definitions` / widget rows and their endpoints stay until a follow-up
  migration decides what to do with the stored definitions. This ADR does not
  authorise deleting them.
* if a CMS-style page composer is wanted later, it should be designed against the
  Vue portal's needs and re-introduce its own authoring surface, not restored
  from the React implementation.
