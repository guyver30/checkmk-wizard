import { Component, Host, h, Prop, Event, EventEmitter } from '@stencil/core';

@Component({
  tag: 'kfds-modal',
  styleUrl: 'kfds-modal.scss',
  shadow: true,
})
export class KfdsModal {
  @Prop() elementId: string;
  @Prop() modalTitle: string;
  @Prop() actions;
  @Prop() visible = false;
  @Prop() showIllustration = false;

  @Event() actionButtonClicked: EventEmitter<string>;

  handleButtonClick(action) {
    this.actionButtonClicked.emit(action);
  }

  render() {
    const actions = Array.isArray(this.actions) ? this.actions : (this.actions ? JSON.parse(this.actions) : []);
    return (
      <Host>
          <div part='modal-wrapper' id={this.elementId} class={this.visible ? "kfds-modal-wrapper visible" : "kfds-modal-wrapper"}>
            <div part='modal-container' class='kfds-modal-container'>
              {this.showIllustration && 
                <div part='modal-illustration-container' class='kfds-modal-illustration-container'>
                </div>
              }
              <div part='modal-main-container' class='kfds-modal-main-container'>
                <div part='modal-title-body-container' class='kfds-modal-title-body-container'>
                  <div part='modal-title-container' class='kfds-modal-title-container'>
                    <h6 part='modal-title' class='kfds-modal-title'>{this.modalTitle}</h6>
                  </div>
                  <div part='modal-body' class='kfds-modal-body'>
                    <slot />
                  </div>
                </div>
              </div>
              {actions.length > 0 && 
              <div part='modal-action-container' class={'kfds-modal-action-container'}>
                {actions.map((action, index) => 
                  <kfds-button 
                  part='modal-action-button'
                  key={index} 
                  element-id={action.elementid} 
                  button-style={action.buttonStyle} 
                  size={action.size} 
                  onButtonClicked={() => this.handleButtonClick(action)}
                  >
                    {action.label}
                  </kfds-button>
                )}
              </div>
              }
            </div>
          </div>
      </Host> 
    );
  }

}
