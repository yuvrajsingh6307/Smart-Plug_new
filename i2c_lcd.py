from lcd_api import LcdApi
from machine import I2C
import time

# PCF8574 pin mapping:
# P0: RS
# P1: RW
# P2: E
# P3: Backlight
# P4: D4
# P5: D5
# P6: D6
# P7: D7

MASK_RS = 0x01
MASK_RW = 0x02
MASK_E  = 0x04
MASK_BL = 0x08

class I2cLcd(LcdApi):
    def __init__(self, i2c, i2c_addr, num_lines, num_columns):
        self.i2c = i2c
        self.i2c_addr = i2c_addr
        self.i2c.writeto(self.i2c_addr, bytes([0]))
        time.sleep_ms(20)   # Wait for LCD to power up
        
        # Send reset sequence (Initialization by instruction)
        self.hal_write_init_nibble(self.LCD_FUNCTION_RESET)
        time.sleep_ms(5)    # wait > 4.1ms
        self.hal_write_init_nibble(self.LCD_FUNCTION_RESET)
        time.sleep_us(150)  # wait > 100us
        self.hal_write_init_nibble(self.LCD_FUNCTION_RESET)
        
        # Switch to 4-bit mode
        self.hal_write_init_nibble(self.LCD_FUNCTION)
        
        # Now we are in 4-bit mode, we can use the normal methods
        super().__init__(num_lines, num_columns)
        
        cmd = self.LCD_FUNCTION
        if num_lines > 1:
            cmd |= self.LCD_FUNCTION_2LINES
        self.hal_write_command(cmd)

    def hal_write_init_nibble(self, nibble):
        # Writes an 8-bit value to the LCD as an initial nibble.
        # Used only during initialization.
        byte = (nibble & 0xF0) | MASK_BL
        self.i2c.writeto(self.i2c_addr, bytes([byte | MASK_E]))
        self.i2c.writeto(self.i2c_addr, bytes([byte]))

    def hal_backlight_on(self):
        self.i2c.writeto(self.i2c_addr, bytes([MASK_BL]))

    def hal_backlight_off(self):
        self.i2c.writeto(self.i2c_addr, bytes([0]))

    def hal_write_command(self, cmd):
        self.hal_write_8bits(cmd, 0)

    def hal_write_data(self, data):
        self.hal_write_8bits(data, MASK_RS)

    def hal_write_8bits(self, value, mode):
        # Write high nibble
        self.hal_write_nibble(value & 0xF0, mode)
        # Write low nibble
        self.hal_write_nibble((value << 4) & 0xF0, mode)

    def hal_write_nibble(self, nibble, mode):
        byte = nibble | mode
        if self.backlight:
            byte |= MASK_BL
        self.i2c.writeto(self.i2c_addr, bytes([byte | MASK_E]))
        self.i2c.writeto(self.i2c_addr, bytes([byte]))