import { Component, h, Prop, Event, EventEmitter } from '@stencil/core';
import { ButtonStyle, ButtonType, ButtonSize } from './kfds-button.enum';

@Component({
  tag: 'kfds-button',
  styleUrl: 'kfds-button.scss',
  shadow: true,
})
export class KfdsButton {
  @Prop() type: ButtonType = ButtonType.Button;
  @Prop() buttonStyle: ButtonStyle = ButtonStyle.Primary;
  @Prop() size: ButtonSize = ButtonSize.Small;
  @Prop() disabled: boolean;
  @Prop() elementId: string;
  @Prop() customClass: string = '';

  @Event() buttonClicked: EventEmitter;

  render() {
    return (
      <button part='button' id={this.elementId} onClick={() => this.handleClick()} type={this.type} disabled={this.disabled} class={this.buttonStyle + ' ' + this.size + ' ' + this.customClass}>
        <slot />
      </button>
    );
  }

  handleClick() {
    this.buttonClicked.emit({
      elementId: this.elementId,
      customClass: this.customClass,
    });
  }

}
