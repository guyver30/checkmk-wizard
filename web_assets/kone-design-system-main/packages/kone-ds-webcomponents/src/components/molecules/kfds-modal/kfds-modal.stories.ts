export default {
    // this creates a ‘Components’ folder and a Modal subfolder
    title: 'Components/Modal',
    tags: ['autodocs'],
    argTypes: {
        actionButtonClicked: { action: 'actionButtonClicked', table: { type: { summary: 'EventEmitter' } } },
    },
    render: ({ ...args }) => {
        return `<kfds-modal actions='${JSON.stringify(args.actions)}' modal-title='${args.modalTitle}' visible=${args.visible}>${args.modalBody}</kfds-modal>`;
    },
    parameters: {
        docs: {
            source: { 
              code: `// React
import { KfdsModal } from '@kone-ds/webcomponents-react';

const [showModal, setShowModal] = useState(false);
const modalActions = [{
    label: 'Cancel',
    buttonStyle: 'tertiary',
    size: 'medium'
  },
  {
    label: 'OK',
    buttonStyle: 'primary',
    size: 'medium'
}];

<a onClick={() => { setShowModal(true) }}> Show Modal</a>
<KfdsModal
    actions={modalActions}
    modalTitle='Modal Title'
    visible={showModal}
    onActionButtonClicked={(event) => { console.log('Action Button Clicked', event); setShowModal(false)}}
>
    Lorem ipsum lorem ipsum
</KfdsModal>`,
            },
          },
    }
};

const modalActions = [{
    label: 'Cancel',
    buttonStyle: 'tertiary',
    size: 'medium'
  },
  {
    label: 'OK',
    buttonStyle: 'primary',
    size: 'medium'
}];


export const Modal = {
    args: {
        actions: modalActions,
        modalTitle: 'Modal dialog',
        visible: true,
        modalBody: 'Long sample text of modal dialog.'
    }
};
