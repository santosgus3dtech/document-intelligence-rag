# Design and fidelity record

The built-in Image Gen tool produced `design-concept.png` before interface
implementation. The complete-screen brief requested a 1536x1024 white document
workspace: 54px header, library rail, evidence conversation and source inspector;
forest-green controls, cool gray canvas, restrained sans typography, thin outline
icons, local-demo identity, real code-native controls, four fictional file rows,
a coolant-filter answer/citation and a yellow source highlight. It explicitly
excluded a marketing hero, invented metrics and static screenshot UI.

The concept is a layout/style reference. The rendered source is always the
actual uploaded/generated document, never the concept's fictional page artwork.

| Comparison | Evidence and result |
|---|---|
| Layout | Desktop uses the concept's 21.2% library / 38.2% conversation / 40.6% inspector split and 54px header at native 1536x1024. |
| Palette | White surfaces, cool gray page canvas, forest green #12614a controls, subtle dividing rules, yellow evidence rectangle. |
| Typography | Locally bundled Inter; prominent 28px main heading with deliberately smaller UI labels, controls and metadata. |
| Controls/icons | Outline document/upload/user/page/arrow/download icons; segmented ranking modes; real form and file input. |
| Evidence interaction | A literal retrieved quote and clickable citation select its document/page and coordinate rectangle; overlay also scales at 150%/200%. |
| Container model | Three dividing rails, flat file rows and one source citation treatment; no decorative card grid. |
| Responsive behavior | At 390x844, Documents / Ask & search / Source panel controls preserve usable source inspection and scrolling. No horizontal body overflow. |

Intentional changes required by implemented behavior: five public demo rows
(six including the restricted memo); exact source titles and literal evidence
instead of concept-only copy; document count instead of a redundant plus button;
explicit search tab, extracted text/table view, zoom, extraction notes, disclosure
of the hashing vector baseline and switchable demo identities. The supplier
suggestion uses a fact actually present in the Portuguese fixture. No invented
claims or content were added to fill the concept.

Material fixes during QA: stale identity-poll responses cannot restore restricted
metadata; requests disable task/mode/scope changes; new questions clear old source
highlights; source loading resets on empty selection; table rows survive indexing;
search icon has an accessible name; mobile upload errors open the visible answer
panel. Original source pages differ from the mockup by design and are inspectable.

Both the concept and final desktop screenshot were inspected with `view_image`
in the final QA pass. The workspace faithfully implements the concept's layout,
palette, hierarchy and interaction treatment with the functional differences above.
