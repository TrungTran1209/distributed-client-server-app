# Protocol

Application messages are serialized according to the schemas in
`collab.common.protocol`. TCP messages are length-framed by
`collab.common.framing`; UDP discovery messages use
`collab.common.udp_protocol`.
