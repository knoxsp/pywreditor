from dataclasses import dataclass


@dataclass
class Validation:
    error_message: str | None = None
    """ The error message. If the message is provided, the form validation is flagged
    as failed """
    warning_message: str | None = None
    """ A warning about a value that is accepted but is likely to cause a problem, such
    as a reference to a component that does not exist. It is shown under the field and
    does not stop the form from being saved. Ignored if there is an error """

    def __post_init__(self):
        """
        Store the validation status in the self.validation flag.
        :return:
        """
        if self.error_message is None:
            self.validation = True
        else:
            self.validation = False
