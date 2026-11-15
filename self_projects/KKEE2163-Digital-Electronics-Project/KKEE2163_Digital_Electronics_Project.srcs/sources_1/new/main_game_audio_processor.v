
// ====================================================================
// MODULE 1: MAIN GAME AUDIO PROCESSOR (With Master Switch Rewind Fix)
// ====================================================================
module main_game_audio_processor(
    input clk,                          // 100 MHz clock from Nexys A7
    input rst,                          // Reset signal
    input master_sw,                    // NEW: Master Kill Switch (Connected to J15)
    input [3:0] current_game_state,     // Received from main game controller
    output aud_pwm,                     // To Nexys A7 Pin A11
    output aud_sd                       // To Nexys A7 Pin D12
);

    // State definitions matching your game architecture
    localparam STATE_HOLD        = 4'd1;
    localparam STATE_INPUT_START = 4'd2;
    localparam STATE_DISP_START  = 4'd3;
    localparam STATE_COUNTDOWN   = 4'd4;
    localparam STATE_THROW       = 4'd5;
    localparam STATE_PULL        = 4'd6;
    localparam STATE_TURN        = 4'd7;
    localparam STATE_CALC        = 4'd8;
    localparam STATE_SHOW_RESULT = 4'd9;

    reg [31:0] melody_note_div;
    reg [31:0] sfx_note_div;
    reg drum_enable;

    wire melody_wave;
    wire sfx_wave;
    
    reg [24:0] tempo_counter;
    reg [3:0] beat_index; 

    // ----------------------------------------------------------------
    // DYNAMIC TEMPO & STUTTER PARAMETERS
    // ----------------------------------------------------------------
    reg [24:0] current_tempo_max;
    reg [24:0] gate_limit;

    always @(*) begin
        case (current_game_state)
            // Active Gameplay States play the 0:34 build-up at 250ms
            STATE_THROW, STATE_PULL, STATE_TURN: begin
                current_tempo_max = 25'd25_000_000; // 250ms per step
                gate_limit        = 25'd20_000_000; // 80% sound window (200ms)
            end
            // Other tracks run at the faster 166ms tempo
            default: begin
                current_tempo_max = 25'd16_600_000; // 166ms per step
                gate_limit        = 25'd13_280_000; // 80% sound window (133ms)
            end
        endcase
    end

    // ----------------------------------------------------------------
    // TIMELINE LOGIC: Track Sequencer
    // ----------------------------------------------------------------
    always @(*) begin
        // Defaults to prevent latching behaviors
        melody_note_div = 32'd0;
        sfx_note_div    = 32'd0;
        drum_enable     = 1'b0;

        case (current_game_state)
            STATE_HOLD: begin
                melody_note_div = 32'd0;
                sfx_note_div    = 32'd0;
                drum_enable     = 1'b0;
            end

            STATE_INPUT_START, STATE_DISP_START: begin
                // Track 1: Intro / Verse Melody (0:00 - 0:24) at 166ms
                drum_enable = 1'b1;
                sfx_note_div = 32'd0;

                if (tempo_counter > gate_limit) begin 
                    melody_note_div = 32'd0; 
                end else begin
                    case(beat_index)
                        4'd0:  melody_note_div = 32'd151685; // E4
                        4'd1:  melody_note_div = 32'd151685; // E4
                        4'd2:  melody_note_div = 32'd0;      // Rest
                        4'd3:  melody_note_div = 32'd151685; // E4
                        4'd4:  melody_note_div = 32'd127551; // G4
                        4'd5:  melody_note_div = 32'd127551; // G4
                        4'd6:  melody_note_div = 32'd0;      // Rest
                        4'd7:  melody_note_div = 32'd127551; // G4
                        4'd8:  melody_note_div = 32'd113636; // A4
                        4'd9:  melody_note_div = 32'd113636; // A4
                        4'd10: melody_note_div = 32'd113636; // A4
                        4'd11: melody_note_div = 32'd95556;  // C5
                        4'd12: melody_note_div = 32'd85131;  // D5
                        4'd13: melody_note_div = 32'd95556;  // C5
                        4'd14: melody_note_div = 32'd113636; // A4
                        4'd15: melody_note_div = 32'd127551; // G4
                    endcase
                end
            end

            STATE_COUNTDOWN: begin
                drum_enable = 1'b0;
                melody_note_div = 32'd0; 
                sfx_note_div  = (tempo_counter < 25'd2_500_000) ? 32'd50000 : 32'd0;
            end

            STATE_THROW, STATE_PULL, STATE_TURN: begin
                // New Track Section: 0:34 - 0:45 Build-up at 250ms
                drum_enable = 1'b0;
                sfx_note_div = 32'd0;

                if (tempo_counter > gate_limit) begin 
                    melody_note_div = 32'd0; // Enforce the 20% silent stutter gap
                end else begin
                    case(beat_index)
                        4'd0:  melody_note_div = 32'd75844;  // E5
                        4'd1:  melody_note_div = 32'd75844;  // E5
                        4'd2:  melody_note_div = 32'd71587;  // F5
                        4'd3:  melody_note_div = 32'd63775;  // G5
                        4'd4:  melody_note_div = 32'd63775;  // G5
                        4'd5:  melody_note_div = 32'd71587;  // F5
                        4'd6:  melody_note_div = 32'd75844;  // E5
                        4'd7:  melody_note_div = 32'd85131;  // D5
                        4'd8:  melody_note_div = 32'd95556;  // C5
                        4'd9:  melody_note_div = 32'd95556;  // C5
                        4'd10: melody_note_div = 32'd85131;  // D5
                        4'd11: melody_note_div = 32'd75844;  // E5
                        4'd12: melody_note_div = 32'd75844;  // E5
                        4'd13: melody_note_div = 32'd85131;  // D5
                        4'd14: melody_note_div = 32'd95556;  // C5
                        4'd15: melody_note_div = 32'd113636; // A4
                    endcase
                end
            end

            STATE_CALC, STATE_SHOW_RESULT: begin
                // Victory Outro Loop
                drum_enable = 1'b0;
                sfx_note_div = 32'd0;
                case(beat_index[1:0])
                    2'd0: melody_note_div = 32'd191110; // C4
                    2'd1: melody_note_div = 32'd151685; // E4
                    2'd2: melody_note_div = 32'd127551; // G4
                    2'd3: melody_note_div = 32'd95556;  // C5
                endcase
            end
            
            default: begin
                melody_note_div = 32'd0;
                sfx_note_div    = 32'd0;
                drum_enable     = 1'b0;
            end
        endcase
    end

    // ----------------------------------------------------------------
    // SEQUENTIAL CLOCK STEP CONTROLLER & AUTO-REWIND LOGIC
    // ----------------------------------------------------------------
    always @(posedge clk or posedge rst) begin
        if (rst) begin
            tempo_counter <= 0;
            beat_index    <= 0;
            
        // --- MASTER SWITCH REWIND FIX ---
        // If J15 is 0, or the game state is HOLD (Idle screen), reset track to 0!
        end else if (master_sw == 1'b0 || current_game_state == STATE_HOLD) begin
            tempo_counter <= 0;
            beat_index    <= 0;
        // --------------------------------
        
        end else begin
            if (tempo_counter >= current_tempo_max) begin
                tempo_counter <= 0;
                beat_index    <= beat_index + 1; 
            end else begin
                tempo_counter <= tempo_counter + 1;
            end
        end
    end
    
    // ----------------------------------------------------------------
    // HARDWARE GENERATORS
    // ----------------------------------------------------------------
    note_generator melody_gen (
        .clk(clk), .rst(rst), .note_div(melody_note_div), .audio_out(melody_wave)
    );

    note_generator sfx_gen (
        .clk(clk), .rst(rst), .note_div(sfx_note_div), .audio_out(sfx_wave)
    );

    // Dynamic White Noise percussion step divider
    wire drum_clk_divider = (tempo_counter[14] && drum_enable); 

    // ----------------------------------------------------------------
    // NOISE-FREE HIGH-SPEED PWM DAC MIXER
    // ----------------------------------------------------------------
    wire [1:0] audio_sum = melody_wave + drum_clk_divider + sfx_wave;
    
    reg [1:0] pwm_counter;
    always @(posedge clk or posedge rst) begin
        if (rst) pwm_counter <= 2'b0;
        else     pwm_counter <= pwm_counter + 1;
    end

    wire mixed_pwm_out = (pwm_counter < audio_sum) ? 1'b1 : 1'b0;

    // --- MUTE FIX INJECTED HERE ---
    // Physical audio will output nothing if J15 is 0 or game is in HOLD state
    assign aud_pwm = (master_sw == 1'b0 || current_game_state == STATE_HOLD) ? 1'b0 : mixed_pwm_out;
    assign aud_sd  = 1'b1; 

endmodule


// ====================================================================
// MODULE 2: CLOCK DIVIDER SQUARE WAVE GENERATOR
// ====================================================================
module note_generator(
    input clk,
    input rst,
    input [31:0] note_div,
    output reg audio_out
);
    reg [31:0] clk_counter;

    always @(posedge clk or posedge rst) begin
        if (rst) begin
            clk_counter <= 0;
            audio_out   <= 0;
        end else if (note_div == 0) begin
            audio_out   <= 0; 
        end else begin
            if (clk_counter >= note_div) begin
                clk_counter <= 0;
                audio_out   <= ~audio_out; 
            end else begin
                clk_counter <= clk_counter + 1;
            end
        end
    end
endmodule