import { Component, Host, h, Prop, State, Event, EventEmitter } from '@stencil/core';
import CloseCrossIcon from '@kone-ds/assets/dist/icons/close-cross.svg';
import { MessagePosition, MessageType } from './kfds-message.enum';

@Component({
  tag: 'kfds-message',
  styleUrl: 'kfds-message.scss',
  shadow: true,
})
export class KfdsMessage {
  @Prop() type: string = MessageType.Info;
  @Prop() position: string = MessagePosition.Top;
  @Prop() elementId: string;
  @Prop() messageTitle: string;
  @Prop() customClass: string = '';
  @Prop() actions;
  @State() showMessage = true;

  @Event() actionButtonClicked: EventEmitter<string>;

  getIcon() {
    switch(this.type) {
      case MessageType.Info:
        return <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path fill-rule="evenodd" clip-rule="evenodd" d="M1 8C1 11.866 4.13403 15 8 15C11.866 15 15 11.866 15 8C15 4.13403 11.866 1 8 1C4.13403 1 1 4.13403 1 8ZM7.39999 11.9997V7H8.59999V11.9997H7.39999ZM8.00001 5.80001C8.44184 5.80001 8.80001 5.44184 8.80001 5.00001C8.80001 4.55818 8.44184 4.20001 8.00001 4.20001C7.55818 4.20001 7.20001 4.55818 7.20001 5.00001C7.20001 5.44184 7.55818 5.80001 8.00001 5.80001Z" fill="#1450F5"/>
        </svg>
      case MessageType.Success:
        return <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path fill-rule="evenodd" clip-rule="evenodd" d="M8 15C11.866 15 15 11.866 15 8C15 4.13401 11.866 1 8 1C4.13401 1 1 4.13401 1 8C1 11.866 4.13401 15 8 15ZM11.3536 6.35359L7.35359 10.3536C7.15833 10.5489 6.84175 10.5489 6.64648 10.3536L4.64648 8.35359L5.35359 7.64648L7.00004 9.29293L10.6465 5.64648L11.3536 6.35359Z" fill="#1ED273"/>
        </svg>       
      case MessageType.Warning:
        return <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path fill-rule="evenodd" clip-rule="evenodd" d="M1 8C1 11.866 4.13403 15 8 15C11.866 15 15 11.866 15 8C15 4.13403 11.866 1 8 1C4.13403 1 1 4.13403 1 8ZM7.39999 11.9997V7H8.59999V11.9997H7.39999ZM8.00001 5.80001C8.44184 5.80001 8.80001 5.44184 8.80001 5.00001C8.80001 4.55818 8.44184 4.20001 8.00001 4.20001C7.55818 4.20001 7.20001 4.55818 7.20001 5.00001C7.20001 5.44184 7.55818 5.80001 8.00001 5.80001Z" fill="#FFA023"/>
        </svg>
      case MessageType.Error:
        return <svg id="warning-triangle-filled" width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path fill-rule="evenodd" clip-rule="evenodd" d="M15.3453 13.1171C15.4465 13.2998 15.4998 13.507 15.5 13.718C15.5002 13.929 15.4472 14.1363 15.3463 14.3192C15.2455 14.5021 15.1003 14.6542 14.9254 14.7602C14.7505 14.8661 14.5519 14.9223 14.3496 14.9231H1.65041C1.4481 14.9223 1.24953 14.8661 1.0746 14.7602C0.89966 14.6542 0.754498 14.5021 0.653653 14.3192C0.552809 14.1363 0.499822 13.929 0.5 13.718C0.50018 13.507 0.553519 13.2998 0.654675 13.1171L7.00427 1.67909C7.10466 1.49614 7.24963 1.34409 7.42448 1.23834C7.59933 1.1326 7.79787 1.0769 8 1.0769C8.20213 1.0769 8.40067 1.1326 8.57552 1.23834C8.75037 1.34409 8.89534 1.49614 8.99573 1.67909L15.3453 13.1171ZM8.60004 10.3077V5.69231H7.40004V10.3077H8.60004ZM8.60001 11.4615H7.40001V12.6615H8.60001V11.4615Z" fill="#FF5F28"/>
        </svg>;             
    }
  }

  removeMessage() {
    this.showMessage = false;
  }

  handleButtonClick(action) {
    this.actionButtonClicked.emit(action);
  }

  render() {
    const actions = Array.isArray(this.actions) ? this.actions : (this.actions ? JSON.parse(this.actions) : []);
    return (
      <Host>
        {this.showMessage ?
          <div part='message-container' id={this.elementId} class={this.type + ' kfds-message-container ' + this.position + ' ' + this.customClass}>
            <div part='message-title-container' class={'kfds-message-title-container'}>
              <span part='message-icon' class='kfds-message-icon'>{this.getIcon()}</span>
              <span part='message-title' class='kfds-message-title'>{this.messageTitle}</span>
              <a part='message-close' class='kfds-message-close' onClick={() => this.removeMessage()}>
                <img src={CloseCrossIcon} />
              </a>
            </div>
            <div part='message-body' class={'kfds-message-body'}>
              <slot />
            </div>
                {actions.length > 0 && 
                <div part='message-button-container' class={'kfds-message-button-container'}>
                  {actions.map((action, index) => 
                    <kfds-button 
                    part='message-button'
                    key={index} 
                    onButtonClicked={() => this.handleButtonClick(action)}
                    element-id={action.elementId}
                    button-style={action.buttonStyle}
                    size={action.size}
                    >   
                    {action.label}               
                    </kfds-button>
                  )}
                </div>
                }
              </div>
            : null }
      </Host> 
    );
  }

}
