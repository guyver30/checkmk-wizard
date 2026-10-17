// The `tag_device_type` choices the dashboard offers when an operator changes a host's device
// type in edit mode. Single source of truth is device_types.json at the repo root, the same file
// the wizard seeds the Checkmk `device_type` tag group from (and whose entries name the icon
// files in assets/icons/device-types/). deploy/dashboard.Containerfile copies it into the build
// context so this relative import resolves the same way in the image as in a checkout.
//
// Checkmk's REST API rejects a tag value that is not a choice of the tag group, and the wizard
// never updates the group's choice list on an existing site, so a type added to the JSON file
// alone is not yet writable there (docs/ -> dashboard-react/README.md section 5b has the steps).

import deviceTypes from "../../../device_types.json";

export const DEVICE_TYPES: readonly string[] = deviceTypes;

// The options for a host's current type: all known types, plus the host's own value when it is
// not one of them (for example `unknown`, or a type removed from the file), so the Select never
// shows a blank for a value Checkmk really holds. `other` is first in the file by contract.
export function deviceTypeOptions(current: string | null | undefined): string[] {
  return current && !DEVICE_TYPES.includes(current) ? [...DEVICE_TYPES, current] : [...DEVICE_TYPES];
}
