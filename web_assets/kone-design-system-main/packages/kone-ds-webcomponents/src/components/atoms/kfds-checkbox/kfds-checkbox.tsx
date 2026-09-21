import { Component, Host, h, Prop, Event, EventEmitter } from '@stencil/core';
import { CheckboxSize, CheckboxOrientation, CheckboxOption } from './kfds-checkbox.enum';

@Component({
  tag: 'kfds-checkbox',
  styleUrl: 'kfds-checkbox.scss',
  shadow: true,
})
export class KfdsCheckbox {
  @Prop() label = '';
  @Prop() name = '';
  @Prop() options: CheckboxOption[] | any;
  @Prop() selectedOptions;
  @Prop() disabled = false;
  @Prop() required = false;
  @Prop() size: CheckboxSize = CheckboxSize.Small;
  @Prop() orientation: CheckboxOrientation = CheckboxOrientation.Vertical;
  @Prop() elementId: string;
  @Prop() customClass: string = '';

  @Event() checkboxClicked: EventEmitter<string[]>;

  handleCheckboxClick(optionValue: string) {
    const index = this.selectedOptions.indexOf(optionValue);
    if (index > -1) {
      this.selectedOptions.splice(index, 1);
    } else {
      this.selectedOptions.push(optionValue);
    }
    this.checkboxClicked.emit(this.selectedOptions);
  }

  render() {
    const options = (Array.isArray(this.options) ? this.options : JSON.parse(this.options));
    const selectedOptions = (Array.isArray(this.selectedOptions) ? this.selectedOptions : JSON.parse(this.selectedOptions));
    return (
      <Host>
        <div part='checkbox-group' id={this.elementId} class={this.size + ' kfds-checkbox-group ' + this.orientation + ' ' + this.customClass}>
          <labal part='checkbox-group-label-container' class={'kfds-checkbox-group-label-container'}>
            <span part='checkbox-group-label' class={'kfds-checkbox-group-label'}>{this.label}</span> 
            {this.required && <span class="kfds-checkbox-group-required">*</span>}
          </labal>
          <div part='checkbox-group-container' class={'kfds-checkbox-group-container'}>
            {options.map((option, index) => 
              <div part='checkbox-container' class={'kfds-checkbox-container ' + (this.disabled ? 'disabled' : '')} key={index}>
                <div part='checkbox' class={'kfds-checkbox'}>
                  <input part='checkbox-input' type="checkbox" onClick={() => this.handleCheckboxClick(option.value)} checked={selectedOptions.includes(option.value)} disabled={this.disabled} id={option.id} name={this.name} value={option.value} />
                  <label part='checkbox-label'>{option.label}</label>
                </div>
                <label part='checkbox-hint-text' class={'kfds-checkbox-hint-text'}>{option.hintText}</label>
              </div>
            )}
          </div>
        </div>    
      </Host>
    );
  }

}
