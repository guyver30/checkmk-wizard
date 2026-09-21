import { SnackbarHorizontalPosition, SnackbarVerticalPosition, SnackbarType } from './kfds-snackbar.enum';

export default {
  // this creates a ‘Components’ folder and a Snackbar subfolder
  title: 'Components/Snackbar',
  tags: ['autodocs'],
  argTypes: {
    type: {
      control: { type: 'select' },
      options: [SnackbarType.Info, SnackbarType.Success, SnackbarType.Warning, SnackbarType.Error],
    },
    actionLinkClicked: { action: 'actionLinkClicked', table: { type: { summary: 'EventEmitter' } } },
  },
  render: ({ ...args }) => {
    return `<kfds-snackbar actions='${JSON.stringify(args.actions)}' duration=${args.duration} auto-hide=${args.autoHide} type='${args.type}' message='${args.message}' show-close=${
      args.showClose
    } vertical-position='${args.verticalPosition}' horizontal-position='${args.horizontalPosition}' visible=${args.visible}></kfds-snackbar>`;
  },
  parameters: {
    docs: {
        source: { 
          code: `// React
import { KfdsSnackbar } from '@kone-ds/webcomponents-react';
import { SnackbarHorizontalPosition, SnackbarType, SnackbarVerticalPosition } from '@kone-ds/webcomponents';

const [showSnackBar, setShowSnackBar] = useState(false);
const snackbarActions = [
  {
    label: 'Link 1',
    href: 'option1',
  },
  {
    label: 'Link 2',
    href: 'option2',
  },
];

<a onClick={() => { setShowSnackBar(true) }}>Show Snackbar</a>
<KfdsSnackbar
  visible={showSnackBar}
  type={SnackbarType.Info}
  horizontal-position={SnackbarHorizontalPosition.Left}
  vertical-position={SnackbarVerticalPosition.Top}
  message='Snackbar Message'
  duration={5000}
  actions={snackbarActions}
  onActionLinkClicked={(event) => console.log('Action Link Clicked', event)}
/>`,
        },
      },
}
};

const snackbarActions = [
  {
    label: 'Link 1',
    href: 'option1',
  },
  {
    label: 'Link 2',
    href: 'option2',
  },
];

export const InfoSnackbar = {
  args: {
    type: SnackbarType.Info,
    actions: snackbarActions.slice(0, 1),
    message: 'Long title text',
    autoHide: false,
    duration: 10000,
    horizontalPosition: SnackbarHorizontalPosition.Left,
    verticalPosition: SnackbarVerticalPosition.Bottom,
    visible: true,
  },
};

export const SuccessSnackbar = {
  args: {
    type: SnackbarType.Success,
    actions: snackbarActions,
    message: 'Long title text',
    showClose: false,
    autoHide: false,
    duration: 10000,
    horizontalPosition: SnackbarHorizontalPosition.Right,
    verticalPosition: SnackbarVerticalPosition.Bottom,
    visible: true,
  },
};

export const WarningSnackbar = {
  args: {
    type: SnackbarType.Warning,
    actions: snackbarActions,
    message: 'Long title text',
    autoHide: false,
    duration: 10000,
    horizontalPosition: SnackbarHorizontalPosition.Left,
    verticalPosition: SnackbarVerticalPosition.Top,
    visible: true,
  },
};

export const ErrorSnackbar = {
  args: {
    type: SnackbarType.Error,
    message: 'Long title text',
    actions: snackbarActions,
    duration: 10000,
    autoHide: false,
    horizontalPosition: SnackbarHorizontalPosition.Right,
    verticalPosition: SnackbarVerticalPosition.Top,
    visible: true,
  },
};
