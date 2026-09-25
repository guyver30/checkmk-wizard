---
quick_id: 260925-pc7
status: complete
---
# Summary
- Icons renamed: circle→other, api→E-link, secured→ACS, videocam→Multimedia, internet→NetworkDevice, controls→GroupController.
- `mapIcons.ts`: glob-loaded; fallback `other.svg`; new `deviceTypeMaskUrl`.
- `treeModel`: `typeIcon` → `deviceType`; `TreeNode` renders the SVG as a CSS mask; `deviceTypeIcon()` removed.
- Behaviour change: `unknown` (missing tag group) no longer has its own question-circle icon; dropping `unknown.svg` in restores one.
- 344 vitest tests pass; typecheck clean. Docs: dashboard-react/README.md §5b.
