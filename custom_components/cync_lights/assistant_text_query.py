import google.auth.transport.grpc
import google.auth.transport.requests
import google.oauth2.credentials
from google.assistant.embedded.v1alpha2 import (embedded_assistant_pb2,embedded_assistant_pb2_grpc)

ASSISTANT_API_ENDPOINT = 'embeddedassistant.googleapis.com'
GRPC_DEADLINE = 60 * 3 + 5

class GoogleAssistantTextRequest():

    def __init__(self, credentials):
        self.credentials = credentials
        self.http_request = google.auth.transport.requests.Request()
        self.grpc_channel = None
        self.assistant = None

    def assist(self, text_query):

        self.grpc_channel = google.auth.transport.grpc.secure_authorized_channel(self.credentials, self.http_request, ASSISTANT_API_ENDPOINT)
        self.assistant = embedded_assistant_pb2_grpc.EmbeddedAssistantStub(self.grpc_channel)

        def iter_assist_requests():
            config = embedded_assistant_pb2.AssistConfig(
                audio_out_config=embedded_assistant_pb2.AudioOutConfig(
                    encoding='LINEAR16',
                    sample_rate_hertz=16000,
                    volume_percentage=0,
                ),
                dialog_state_in=embedded_assistant_pb2.DialogStateIn(
                    language_code = 'en-US',
                    conversation_state = None,
                    is_new_conversation = True,
                ),
                device_config=embedded_assistant_pb2.DeviceConfig(
                    device_id='5a1b2c3d4',
                    device_model_id='assistant',
                ),
                text_query=text_query
            )
            req = embedded_assistant_pb2.AssistRequest(config=config)
            yield req

        [resp for resp in self.assistant.Assist(iter_assist_requests(),GRPC_DEADLINE)]
        self.credentials.refresh(self.http_request)
