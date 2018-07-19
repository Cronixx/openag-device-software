# Import standard python libraries
import fcntl, io, time, logging, threading, struct
from typing import Optional, List

# # Import package elements
from device.comms.i2c2.device_io import DeviceIO
from device.comms.i2c2.utilities import make_i2c_rdwr_data
from device.comms.i2c2.peripheral_simulator import PeripheralSimulator
from device.comms.i2c2.mux_simulator import MuxSimulator
from device.comms.i2c2.exceptions import InitError, WriteError, ReadError, MuxError

# Import device utilities
from device.utilities.logger import Logger
from device.utilities.functiontools import retry
from device.utilities.bitwise import byte_str


class I2C(object):
    """I2C communication device. Can communicate with device directly or
    via an I2C mux."""

    def __init__(
        self,
        name: str,
        bus: int,
        address: int,
        mux: Optional[int],
        channel: Optional[int],
        mux_simulator: Optional[MuxSimulator],
        PeripheralSimulator: Optional[PeripheralSimulator],
        verify_device: bool = True,
    ) -> None:

        # Initialize passed in parameters
        self.name = name
        self.bus = bus
        self.address = address
        self.mux = mux
        self.channel = channel

        # Initialize logger instance
        logger_name = "I2C({})".format(self.name)
        self.logger = Logger(name=logger_name, dunder_name=__name__)
        self.logger.debug("Initializing communication")

        # Verify mux config
        if self.mux != None and self.channel == None:
            raise InitError("Mux requires channel value to be set") from ValueError

        # Initialize io
        if PeripheralSimulator != None:
            self.logger.debug("Using simulated io stream")
            self.io = PeripheralSimulator(  # type: ignore
                name, bus, address, mux, channel, mux_simulator
            )
        else:
            self.logger.debug("Using device io stream")
            self.io = DeviceIO(name, bus)

        # Verify mux exists
        if self.mux != None:
            self.verify_mux()

        # Verify device exists
        if verify_device:
            self.verify_device()

        # Successfully initialized!
        self.logger.debug("Initialization successful")

    def verify_mux(self) -> None:
        """Verifies mux exists by trying to set it to a channel."""
        try:
            self.logger.debug("Verifying mux exists")
            byte = self.set_mux(self.mux, self.channel, retry=True)
        except MuxError as e:
            message = "Unable to verify mux exists"
            raise InitError(message, logger=self.logger) from e

    def verify_device(self) -> None:
        """Verifies device exists by trying to read a byte from it."""
        try:
            self.logger.debug("Verifying device exists")
            byte = self.read(1, retry=True)
        except ReadError as e:
            message = "Unable to verify device exists, read error"
            raise InitError(message, logger=self.logger) from e
        except MuxError as e:
            message = "Unable to verify device exists, mux error"
            raise InitError(message, logger=self.logger) from e

    @retry((WriteError, MuxError), tries=5, delay=0.2, backoff=3, lock=True)
    def write(self, bytes_: bytes, retry: bool = False) -> None:
        """Writes byte list to device. Converts byte list to byte array then
        sends bytes. Returns error message."""
        self.manage_mux("write bytes")
        self.logger.debug("Writing bytes: {}".format(byte_str(bytes_)))
        self.io.write(self.address, bytes_)

    @retry((ReadError, MuxError), tries=5, delay=0.2, backoff=3, lock=True)
    def read(self, num_bytes: int, retry: bool = False) -> bytes:
        """Reads num bytes from device. Returns byte array."""
        self.manage_mux("read bytes")
        self.logger.debug("Reading {} bytes".format(num_bytes))
        bytes_ = bytes(self.io.read(self.address, num_bytes))
        self.logger.debug("Read bytes: {}".format(byte_str(bytes_)))
        return bytes_

    @retry((ReadError, MuxError), tries=5, delay=0.2, backoff=3, lock=True)
    def read_register(self, register: int, retry: bool = False) -> int:
        """ Reads byte stored in register at address. """
        self.manage_mux("read register")
        self.logger.debug("Reading register: 0x{:02X}".format(register))
        return int(self.io.read_register(self.address, register))

    @retry((WriteError, MuxError), tries=5, delay=0.2, backoff=3, lock=True)
    def write_register(self, register: int, value: int, retry: bool = False) -> None:
        self.manage_mux("write register")
        message = "Writing register: 0x{:02X}, value: 0x{:02X}".format(register, value)
        self.logger.debug(message)
        self.io.write_register(self.address, register, value)

    @retry(MuxError, tries=5, delay=0.2, backoff=3, lock=True)
    def set_mux(self, mux: int, channel: int, retry: bool = False) -> None:
        """Sets mux to channel"""
        self.logger.debug("Setting mux 0x{:02X} to channel {}".format(mux, channel))
        channel_byte = 0x01 << channel
        try:
            self.io.write(mux, bytes([channel_byte]))
        except WriteError as e:
            raise MuxError("Unable to set mux", logger=self.logger) from e

    def manage_mux(self, message: str) -> None:
        """Sets mux if enabled."""
        if self.mux != None:
            self.logger.debug("Managing mux to {}".format(message))
            self.set_mux(self.mux, self.channel, retry=False)