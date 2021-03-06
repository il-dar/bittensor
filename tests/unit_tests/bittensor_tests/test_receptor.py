import grpc
import torchvision.transforms as transforms
import torch
import unittest
import bittensor
import pytest
import torchvision

from unittest.mock import MagicMock
import bittensor.serialization as serialization
from munch import Munch

config = bittensor.receptor.Receptor.build_config(); config.receptor.do_backoff = False
wallet = bittensor.wallet.Wallet( config )
neuron = bittensor.proto.Neuron(
    version = bittensor.__version__,
    public_key = wallet.keypair.public_key,
    address = '0.0.0.0',
    port = 22424,
)
receptor = bittensor.receptor.Receptor( neuron, config=config, wallet=wallet )
channel = grpc.insecure_channel('localhost',
            options=[('grpc.max_send_message_length', -1),
                     ('grpc.max_receive_message_length', -1)])          
stub = bittensor.grpc.BittensorStub(channel)

def test_receptor_neuron_text():
    x = torch.tensor([[1,2,3,4],[5,6,7,8]], dtype=torch.long)
    out, ops = receptor.forward( x, bittensor.proto.Modality.TEXT)
    print (out, ops)
    assert ops.item() == bittensor.proto.ReturnCode.Unavailable
    assert list(out.shape) == [2, 4, bittensor.__network_dim__]

def test_receptor_neuron_image():
    x = torch.tensor([ [ [ [ [ 1 ] ] ] ] ])
    out, ops = receptor.forward( x, bittensor.proto.Modality.IMAGE)
    assert ops.item() == bittensor.proto.ReturnCode.Unavailable
    assert list(out.shape) == [1, 1, bittensor.__network_dim__]

def test_receptor_neuron_tensor():
    x = torch.rand(3, 3, bittensor.__network_dim__)
    out, ops = receptor.forward( x, bittensor.proto.Modality.TENSOR)
    assert ops.item() == bittensor.proto.ReturnCode.Unavailable
    assert list(out.shape) == [3, 3, bittensor.__network_dim__]

def test_receptor_neuron_request_empty():
    x = torch.tensor([])
    out, ops = receptor.forward( x, bittensor.proto.Modality.TEXT)
    assert ops.item() == bittensor.proto.ReturnCode.EmptyRequest
    assert list(out.shape) == [0]

def test_receptor_neuron_mock_server():
    y = torch.rand(3, 3, bittensor.__network_dim__)
    
    serializer = serialization.get_serializer( serialzer_type = bittensor.proto.Serializer.MSGPACK )
    y_serialized = serializer.serialize(y, modality = bittensor.proto.Modality.TENSOR, from_type = bittensor.proto.TensorType.TORCH)
            
    mock_return_val = bittensor.proto.TensorMessage(
            version = bittensor.__version__,
            public_key = wallet.keypair.public_key,
            return_code = bittensor.proto.ReturnCode.Success,
            tensors = [y_serialized])

    stub.Forward = MagicMock( return_value=mock_return_val )
    receptor.stub = stub

    x = torch.rand(3, 3, bittensor.__network_dim__)
    out, ops = receptor.forward(x, bittensor.proto.Modality.TENSOR)
    assert ops.item() == bittensor.proto.ReturnCode.Success
    assert list(out.shape) == [3, 3, bittensor.__network_dim__]


def test_receptor_neuron_serve_timeout():
    y = torch.rand(3, 3, bittensor.__network_dim__)
    
    serializer = serialization.get_serializer( serialzer_type = bittensor.proto.Serializer.MSGPACK )
    y_serialized = serializer.serialize(y, modality = bittensor.proto.Modality.TENSOR, from_type = bittensor.proto.TensorType.TORCH)
            
    mock_return_val = bittensor.proto.TensorMessage(
            version = bittensor.__version__,
            public_key = wallet.keypair.public_key,
            return_code = bittensor.proto.ReturnCode.Timeout,
            tensors = [y_serialized])

    stub.Forward = MagicMock( return_value=mock_return_val )
    receptor.stub = stub

    x = torch.rand(3, 3, bittensor.__network_dim__)
    out, ops = receptor.forward(x, bittensor.proto.Modality.TENSOR)
    assert ops.item() == bittensor.proto.ReturnCode.Timeout
    assert list(out.shape) == [3, 3, bittensor.__network_dim__]


def test_receptor_neuron_serve_empty():                
    mock_return_val = bittensor.proto.TensorMessage(
            version = bittensor.__version__,
            public_key = wallet.keypair.public_key,
            return_code = bittensor.proto.ReturnCode.Success,
            tensors = [])

    stub.Forward = MagicMock( return_value=mock_return_val )
    receptor.stub = stub

    x = torch.rand(3, 3, bittensor.__network_dim__)
    out, ops = receptor.forward(x, bittensor.proto.Modality.TENSOR)
    assert ops.item() == bittensor.proto.ReturnCode.EmptyResponse
    assert list(out.shape) == [3, 3, bittensor.__network_dim__]


def test_receptor_neuron_mock_server_deserialization_error():
    y = dict() # bad response
    mock_return_val = bittensor.proto.TensorMessage(
            version = bittensor.__version__,
            public_key = wallet.keypair.public_key,
            return_code = bittensor.proto.ReturnCode.Success,
            tensors = [y])

    stub.Forward = MagicMock( return_value=mock_return_val )
    receptor.stub = stub

    x = torch.rand(3, 3, bittensor.__network_dim__)
    out, ops = receptor.forward(x, bittensor.proto.Modality.TENSOR)
    assert ops.item() == bittensor.proto.ReturnCode.ResponseDeserializationException
    assert list(out.shape) == [3, 3, bittensor.__network_dim__]


def test_receptor_neuron_mock_server_shape_error():
    y = torch.rand(1, 3, bittensor.__network_dim__)

    serializer = serialization.get_serializer( serialzer_type = bittensor.proto.Serializer.MSGPACK )
    y_serialized = serializer.serialize(y, modality = bittensor.proto.Modality.TENSOR, from_type = bittensor.proto.TensorType.TORCH)
   
    mock_return_val = bittensor.proto.TensorMessage(
            version = bittensor.__version__,
            public_key = wallet.keypair.public_key,
            return_code = bittensor.proto.ReturnCode.Success,
            tensors = [y_serialized])

    stub.Forward = MagicMock( return_value=mock_return_val )
    receptor.stub = stub

    x = torch.rand(3, 3, bittensor.__network_dim__)
    out, ops = receptor.forward(x, bittensor.proto.Modality.TENSOR)
    assert ops.item() == bittensor.proto.ReturnCode.ResponseShapeException
    assert list(out.shape) == [3, 3, bittensor.__network_dim__]


def test_receptor_neuron_server_response_with_nans():
    import numpy as np
    y = torch.rand(3, 3, bittensor.__network_dim__)
    y[0][0][0] = np.nan

    serializer = serialization.get_serializer( serialzer_type = bittensor.proto.Serializer.MSGPACK )
    y_serialized = serializer.serialize(y, modality = bittensor.proto.Modality.TENSOR, from_type = bittensor.proto.TensorType.TORCH)
   
    mock_return_val = bittensor.proto.TensorMessage(
            version = bittensor.__version__,
            public_key = wallet.keypair.public_key,
            return_code = bittensor.proto.ReturnCode.Success,
            tensors = [y_serialized])

    stub.Forward = MagicMock( return_value=mock_return_val )
    receptor.stub = stub

    x = torch.rand(3, 3, bittensor.__network_dim__)
    out, ops = receptor.forward(x, bittensor.proto.Modality.TENSOR)
    assert ops.item() == bittensor.proto.ReturnCode.Success
    assert out[0][0][0] == 0



if __name__ == "__main__":
    test_receptor_neuron_text ()
    test_receptor_neuron_image ()
    test_receptor_neuron_tensor ()
    test_receptor_neuron_request_empty ()
    test_receptor_neuron_mock_server ()
    test_receptor_neuron_mock_server_deserialization_error ()
    test_receptor_neuron_mock_server_shape_error ()