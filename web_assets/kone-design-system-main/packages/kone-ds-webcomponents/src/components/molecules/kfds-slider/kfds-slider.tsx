import { Component, h, Element, Host, Prop, Event, EventEmitter, State } from '@stencil/core';
import InfoIcon from '@kone-ds/assets/dist/icons/info.svg';

@Component({
  tag: 'kfds-slider',
  styleUrl: 'kfds-slider.scss',
  shadow: true,
})
export class KfdsSlider {
  @Element() host: HTMLKfdsSliderElement;

  // Slider Props
  @Prop() elementId: string;
  @Prop() sliderClass: string = '';
  @Prop() min: number = 0;
  @Prop() max: number = 100;
  @Prop() disabled: boolean = false;
  @Prop() selectedValue: number;
  @State() value;

  // Label Props
  @Prop() label: string;
  @Prop() showLabel: boolean;
  @Prop() unit: string;
  @Prop() supportingText: string;
  @Prop() showSupportingText: boolean;
  @Prop() customClass: string;

  // UI Props
  @Prop() required: boolean;
  @Prop() showNumberInput: boolean;

  // Internal Slider status @State not encouraged to use in Web Component
  @State() sliderState: 'active' | 'error' | 'disabled' | '' = '';

  @Event() inputChange: EventEmitter<string>;
  @Event() inputBlur: EventEmitter<string>;

  constructor() {}

  componentWillLoad() {
    this.value = !isNaN(this.selectedValue) ? this.selectedValue : 0;
    this.sliderState = this.disabled ? 'disabled' : '';
  }
  handleChange(event: any) {
    if (isNaN(event.target.value)) {
      this.sliderState = 'error';
      return;
    }

    this.sliderState = 'active';
    this.value = event.target.value;
    this.inputChange.emit(event.target.value);
  }

  handleRangeInputChange(event: any) {
    this.value = Number(event.target.value);
    this.sliderState = 'active';
    this.inputChange.emit(this.value);
  }

  getLinePosition() {
    return {
      width: ((this.value - this.min) * 100) / (this.max - this.min) + '%',
    };
  }

  getThumbPosition() {
    if (!this.value) return { left: '0%', right: '0%' };

    const linePosition = ((this.value - this.min) * 100) / (this.max - this.min);

    return { right: 100 - linePosition + '%', left: linePosition + '%' };
  }
  handleBlur(event: any) {
    if (isNaN(event.target.value)) {
      this.sliderState = 'error';
      return;
    }

    this.value = event.target.value;
    this.inputBlur.emit(event.target.value);
  }

  /**
   *
   * Has to be refactored to change the fill color dynamic once this ready https://kone.atlassian.net/browse/KDS-199
   */
  getSupportingTextIcon() {
    switch (this.sliderState) {
      case 'error':
        return (
          <svg id="warning" width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path
              fill-rule="evenodd"
              clip-rule="evenodd"
              d="M1.66415 13.6759L8 2.26271L14.3359 13.676C14.3415 13.6862 14.3461 13.7012 14.3462 13.719C14.3462 13.7369 14.3415 13.7519 14.3359 13.7621C14.3342 13.7652 14.3326 13.7675 14.3313 13.7692H1.66871C1.66736 13.7675 1.66578 13.7652 1.6641 13.7621C1.65848 13.7519 1.65383 13.7369 1.65385 13.719C1.65386 13.7012 1.65856 13.6861 1.66415 13.6759ZM15.5 13.718C15.4998 13.507 15.4465 13.2998 15.3453 13.1171L8.99573 1.67909C8.89534 1.49614 8.75037 1.34409 8.57552 1.23834C8.40067 1.1326 8.20213 1.0769 8 1.0769C7.79787 1.0769 7.59933 1.1326 7.42448 1.23834C7.24963 1.34409 7.10466 1.49614 7.00427 1.67909L0.654675 13.1171C0.55352 13.2998 0.500181 13.507 0.5 13.718C0.499822 13.929 0.552809 14.1363 0.653654 14.3192C0.754499 14.5021 0.89966 14.6542 1.0746 14.7602C1.24953 14.8661 1.4481 14.9223 1.65041 14.9231H14.3496C14.5519 14.9223 14.7505 14.8661 14.9254 14.7602C15.1003 14.6542 15.2455 14.5021 15.3463 14.3192C15.4472 14.1363 15.5002 13.929 15.5 13.718ZM8.59999 10.3269V6H7.39999V10.3269H8.59999ZM8.62307 11.1923H7.42307V12.3923H8.62307V11.1923Z"
              fill="#FF5F28"
            />
          </svg>
        );
      default:
        return <img id="info" src={InfoIcon} />;
    }
  }

  render() {
    return (
      <Host>
        <div part='slider-container' class={'kfds-slider-container'} id={this.elementId}>
          {this.showLabel && (
            <label part='label'>
              {this.label} {this.required && <span class="required">*</span>} {this.unit && <span>({this.unit})</span>}
            </label>
          )}
          <div part='slider-wrapper' class="slider-wrapper">
            <span class={this.disabled ? 'min-value disabled' : 'min-value'}>{this.min}</span>

            <div part='container' class="container">
              <div part='range' class={'range'}>
                <div part='range-content' class="range__content">
                  <div part='range-slider' class={`range__slider${this.sliderState ? ' ' + this.sliderState : ''}`}>
                    <div part='range-line' id="range-line" style={this.getLinePosition()} class={`range__slider-line${this.sliderState ? ' ' + this.sliderState : ''}`}></div>
                  </div>
                  <div part='range-thumb' id="range-thumb" style={this.getThumbPosition()} class={`range__thumb${this.sliderState ? ' ' + this.sliderState : ''}`}></div>
                  <input
                    part='input'
                    onInput={event => this.handleRangeInputChange(event)}
                    type="range"
                    class="range__input"
                    id="range-input"
                    min={this.min}
                    max={this.max}
                    step="1"
                    disabled={this.disabled}
                    value={this.value}
                  />
                </div>
              </div>
            </div>

            <span class={this.disabled ? 'max-value disabled' : 'max-value'}>{this.max}</span>
            {this.showNumberInput && (
              <div part='input-container' class="input-container">
                <input
                  part='number-input'
                  type="text"
                  class={this.sliderState}
                  value={this.value}
                  maxlength={this.max.toString().length}
                  onInput={event => this.handleChange(event)}
                  onBlur={event => this.handleBlur(event)}
                  disabled={this.disabled}
                ></input>
              </div>
            )}
          </div>
          {this.showSupportingText ? (
            <div part='supporting-text-container' class={'supporting-text-container'}>
              {<span part='supporting-text-icon' class={`icon ${this.sliderState}`}>{this.getSupportingTextIcon()}</span>}
              {this.supportingText ? <span part='supporting-text' class={'supporting-text'}>{this.supportingText}</span> : ''}
            </div>
          ) : (
            ''
          )}
        </div>
      </Host>
    );
  }
}
