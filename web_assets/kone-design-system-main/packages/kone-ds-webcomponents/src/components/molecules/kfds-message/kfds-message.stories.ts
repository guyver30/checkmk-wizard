import { MessagePosition, MessageType } from './kfds-message.enum';

export default {
    // this creates a ‘Components’ folder and a Message subfolder
    title: 'Components/Message',
    tags: ['autodocs'],
    argTypes: {
        type: { 
            control: { type: "select" },
            options: [MessageType.Info, MessageType.Success, MessageType.Warning, MessageType.Error] 
        },
        actionButtonClicked: { action: 'actionButtonClicked', table: { type: { summary: 'EventEmitter' } } },
    },
    render: ({ ...args }) => {
        return `<kfds-message actions='${JSON.stringify(args.actions)}' type='${args.type}' message-title='${args.messagetitle}' position='${args.position}'>lorem ipsum lorem ipsum</kfds-message>`;
    },
    parameters: {
        docs: {
            source: { 
              code: `// React
import { KfdsMessage } from '@kone-ds/webcomponents-react';
import { MessagePosition, MessageType } from '@kone-ds/webcomponents';

const messageActions = [{
    label: 'Dismiss',
    buttonStyle: 'borderless',
    size: 'small'
  },
  {
    label: 'Read more',
    buttonStyle: 'tertiary',
    size: 'small'
}];

<KfdsMessage
    actions={messageActions}
    type={MessageType.Info}
    position={MessagePosition.Inline}
    messageTitle='Message Title'
    onActionButtonClicked={(event) => console.log('Action Button Clicked', event)}
>
    Lorem ipsum lorem ipsum
</KfdsMessage>`,
            },
          },
    }
};

const messageActions = [{
    label: 'Dismiss',
    buttonStyle: 'borderless',
    size: 'small'
  },
  {
    label: 'Read more',
    buttonStyle: 'tertiary',
    size: 'small'
}];


export const InfoMessage = { 
    args: {
        type: MessageType.Info,
        actions: messageActions,
        messagetitle: 'Long title text',
        position: MessagePosition.Top
    }
};

export const SuccessMessage = { 
    args: {
        type: MessageType.Success,
        actions: messageActions,
        messagetitle: 'Long title text',
        position: MessagePosition.Top
    }
};

export const InlineWarningMessage = { 
    args: {
        type: MessageType.Warning,
        actions: messageActions,
        messagetitle: 'Long title text',
        position: MessagePosition.Inline
    }
};

export const InlineAlertMessage = { 
    args: {
        type: MessageType.Error,
        messagetitle: 'Long title text',
        actions: [],
        position: MessagePosition.Inline
    }
};
