import { Component, Host, h, Prop, Event, EventEmitter } from '@stencil/core';
import { RadioSize, RadioOrientation, RadioOption } from './kfds-radio.enum';

@Component({
  tag: 'kfds-radio',
  styleUrl: 'kfds-radio.scss',
  shadow: true,
})
export class KfdsRadio {
  @Prop() label = '';
  @Prop() name = '';
  @Prop() options: RadioOption[] | any;
  @Prop() selectedOption;
  @Prop() disabled = false;
  @Prop() required = false;
  @Prop() size: RadioSize = RadioSize.Small;
  @Prop() orientation: RadioOrientation = RadioOrientation.Vertical;
  @Prop() customClass: string = '';
  @Prop() elementId: string;

  @Event() radioClicked: EventEmitter<string>;

  handleRadioClick(optionValue: string) {
    this.selectedOption = optionValue;
    this.radioClicked.emit(this.selectedOption);
  }

  render() {
    const options = (Array.isArray(this.options) ? this.options : JSON.parse(this.options));
    return (
      <Host>
        <div part='radio-group' id={this.elementId} class={this.size + ' kfds-radio-group ' + this.orientation + ' ' + this.customClass}>
          <labal part='radio-group-label-container' class={'kfds-radio-group-label-container'}>
            <span part='radio-group-label' class={'kfds-radio-group-label'}>{this.label}</span> 
            {this.required && <span class="kfds-radio-group-required">*</span>}
          </labal>
          <div part='radio-group-container' class={'kfds-radio-group-container'}>
            {options.map((option, index) => 
              <div part='radio-container ' class={'kfds-radio-container ' + (this.disabled ? 'disabled' : '')} key={index}>
                <div part='radio' class={'kfds-radio'}>
                  <input part='radio-input' type="radio" onClick={() => this.handleRadioClick(option.value)} checked={this.selectedOption === option.value} disabled={this.disabled} id={option.id} name={this.name} value={option.value} />
                  <label part='radio-label'>{option.label}</label>
                </div>
                <label part='radio-hint-text' class={'kfds-radio-hint-text'}>{option.hintText}</label>
              </div>
            )}
          </div>
        </div>
      </Host>
    );
  }

}
