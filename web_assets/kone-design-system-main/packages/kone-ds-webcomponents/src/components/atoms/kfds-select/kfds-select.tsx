import { Component, Host, h, Prop, Event, EventEmitter } from '@stencil/core';
import InfoIcon from '@kone-ds/assets/dist/icons/info.svg';
import { SelectShape, SelectSize, selectOption } from './kfds-select.enum';

@Component({
  tag: 'kfds-select',
  styleUrl: 'kfds-select.scss',
  shadow: true,
})
export class KfdsSelect {
  @Prop() name = '';
  @Prop() options: selectOption[] | any;
  @Prop() selectedOption;
  @Prop() label = '';
  @Prop() placeholder = '';
  @Prop() supportingText = '';
  @Prop() disabled = false;
  @Prop() size: SelectSize = SelectSize.Small;
  @Prop() shape: SelectShape = SelectShape.Rounded;
  @Prop() customClass: string = '';
  @Prop() elementId: string;
  @Prop() required = false;
  @Event() selectChange: EventEmitter<string>;
  @Event() selectBlur: EventEmitter<string>;

  handleChange(event) {
    this.selectChange.emit(event.target.value);
  }

  handleBlur(event) {
    this.selectBlur.emit(event.target.value);
  }

  getSupportingTextIcon() {
    switch(this.customClass) {
      case 'error':
        return <svg id="warning" width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path fill-rule="evenodd" clip-rule="evenodd" d="M1.66415 13.6759L8 2.26271L14.3359 13.676C14.3415 13.6862 14.3461 13.7012 14.3462 13.719C14.3462 13.7369 14.3415 13.7519 14.3359 13.7621C14.3342 13.7652 14.3326 13.7675 14.3313 13.7692H1.66871C1.66736 13.7675 1.66578 13.7652 1.6641 13.7621C1.65848 13.7519 1.65383 13.7369 1.65385 13.719C1.65386 13.7012 1.65856 13.6861 1.66415 13.6759ZM15.5 13.718C15.4998 13.507 15.4465 13.2998 15.3453 13.1171L8.99573 1.67909C8.89534 1.49614 8.75037 1.34409 8.57552 1.23834C8.40067 1.1326 8.20213 1.0769 8 1.0769C7.79787 1.0769 7.59933 1.1326 7.42448 1.23834C7.24963 1.34409 7.10466 1.49614 7.00427 1.67909L0.654675 13.1171C0.55352 13.2998 0.500181 13.507 0.5 13.718C0.499822 13.929 0.552809 14.1363 0.653654 14.3192C0.754499 14.5021 0.89966 14.6542 1.0746 14.7602C1.24953 14.8661 1.4481 14.9223 1.65041 14.9231H14.3496C14.5519 14.9223 14.7505 14.8661 14.9254 14.7602C15.1003 14.6542 15.2455 14.5021 15.3463 14.3192C15.4472 14.1363 15.5002 13.929 15.5 13.718ZM8.59999 10.3269V6H7.39999V10.3269H8.59999ZM8.62307 11.1923H7.42307V12.3923H8.62307V11.1923Z" fill="#FF5F28"/>
        </svg>;
      default:
        return <img id='info' src={InfoIcon} />;        
    }
  }

  render() {
    const options = (Array.isArray(this.options) ? this.options : JSON.parse(this.options));
    return (
      <Host>
        <div part='select-container' id={this.elementId} class={`${this.size} kfds-select-container ${this.customClass}`}>
          <label part='select-label-container' class={'kfds-select-label-container'}>
            <span part='select-label' class={'kfds-select-label'}>{this.label}</span> 
            {this.required && <span class="kfds-select-required">*</span>}
          </label>
          <select part='select' class={this.shape} disabled={this.disabled} name={this.name} onInput={(event) => this.handleChange(event)} onBlur={(event) => this.handleBlur(event)}>
            <option part='empty-option' value="">{this.placeholder}</option>
            {options.map((option) => 
              <option part='option' selected={this.selectedOption === option.value} value={option.value}>{option.label}</option>
            )}
          </select>
          {this.supportingText && this.size !== 'inline' &&
            <span part='select-supporting-text' class={'kfds-select-supporting-text'}>
              {this.getSupportingTextIcon()}
              {this.supportingText}
            </span>
          }
        </div>
      </Host>
    );
  }

}
